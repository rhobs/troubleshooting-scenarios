"""Notification service - polls payments-api and sends payment notifications."""

import logging
import sys
import threading
import time

import requests
from flask import Flask, jsonify
from prometheus_client import Counter, Gauge, generate_latest

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("notification-service")

# --- Prometheus metrics ---
DELIVERIES = Counter(
    "notification_deliveries_total",
    "Total notifications delivered",
    ["status"],
)
LAST_DELIVERY = Gauge(
    "notification_last_delivery_timestamp",
    "Unix timestamp of last successful notification delivery",
)

# --- Global state ---
PAYMENTS_API_URL = "http://payments-api:8080/api/v1/process-payment"
STALE_THRESHOLD = 120  # seconds before readiness fails
last_delivery_time = 0.0
lock = threading.Lock()


def poll_and_notify() -> None:
    global last_delivery_time
    while True:
        try:
            resp = requests.get(PAYMENTS_API_URL, timeout=3)
            if resp.status_code == 200:
                with lock:
                    last_delivery_time = time.time()
                LAST_DELIVERY.set(last_delivery_time)
                DELIVERIES.labels(status="success").inc()
                logger.info("Payment notification delivered")
            else:
                DELIVERIES.labels(status="failed").inc()
                logger.warning("Failed to fetch payment data: HTTP %d", resp.status_code)
        except requests.exceptions.RequestException as e:
            DELIVERIES.labels(status="failed").inc()
            with lock:
                stale_seconds = time.time() - last_delivery_time if last_delivery_time > 0 else 0
            if stale_seconds < 30:
                logger.warning("Cannot reach payments-api: %s", e)
            elif stale_seconds < STALE_THRESHOLD:
                logger.error(
                    "Notification delivery stalled for %ds, payments-api unreachable",
                    int(stale_seconds),
                )
            else:
                logger.error(
                    "Notification pipeline broken, no deliveries for %ds",
                    int(stale_seconds),
                )
        time.sleep(3)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/ready")
def ready():
    with lock:
        stale = time.time() - last_delivery_time if last_delivery_time > 0 else 0
    if last_delivery_time > 0 and stale > STALE_THRESHOLD:
        return jsonify({"status": "stale", "seconds_since_delivery": int(stale)}), 503
    return jsonify({"status": "ready"})


@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": "text/plain; charset=utf-8"}


if __name__ == "__main__":
    logger.info("notification-service starting on port 8080")
    threading.Thread(target=poll_and_notify, daemon=True).start()
    app.run(host="0.0.0.0", port=8080)
