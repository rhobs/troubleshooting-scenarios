"""Checkout service - depends on payments-api for payment verification."""

import logging
import sys
import threading
import time
import uuid

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
logger = logging.getLogger("checkout-service")

# --- Prometheus metrics ---
REQUEST_COUNT = Counter(
    "checkout_requests_total",
    "Total checkout requests",
    ["status"],
)
ERROR_COUNT = Counter(
    "checkout_errors_total",
    "Total checkout errors by type",
    ["type"],
)
DEPENDENCY_UP = Gauge(
    "checkout_dependency_up",
    "Whether a dependency is reachable (1=up, 0=down)",
    ["service"],
)

# --- Global state ---
PAYMENTS_API_URL = "http://payments-api:8080/api/v1/process-payment"
MAX_RETRIES = 3
consecutive_failures = 0
degraded = False
lock = threading.Lock()


def check_payments_api() -> None:
    global consecutive_failures, degraded
    while True:
        try:
            resp = requests.get(PAYMENTS_API_URL, timeout=3)
            if resp.status_code == 200:
                with lock:
                    if consecutive_failures > 0:
                        logger.info(
                            "payments-api reachable again after %d failures, recovering",
                            consecutive_failures,
                        )
                    consecutive_failures = 0
                    degraded = False
                DEPENDENCY_UP.labels(service="payments-api").set(1)
            else:
                _record_failure(f"HTTP {resp.status_code}")
        except requests.exceptions.ConnectionError:
            _record_failure("Connection refused")
        except requests.exceptions.Timeout:
            _record_failure("Timeout")
        except requests.exceptions.RequestException as e:
            _record_failure(str(e))
        time.sleep(2)


def _record_failure(reason: str) -> None:
    global consecutive_failures, degraded
    with lock:
        consecutive_failures += 1
        DEPENDENCY_UP.labels(service="payments-api").set(0)

        if consecutive_failures <= MAX_RETRIES:
            logger.warning(
                "Retry %d/%d for payment verification",
                consecutive_failures,
                MAX_RETRIES,
            )
            ERROR_COUNT.labels(type="connection_error").inc()
        else:
            if not degraded:
                logger.error(
                    "Failed to reach payments-api: %s (payments-api:8080)", reason
                )
                logger.error(
                    "payments-api unreachable after %d retries, marking service degraded",
                    MAX_RETRIES,
                )
                degraded = True
            ERROR_COUNT.labels(type="connection_error").inc()


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/ready")
def ready():
    if degraded:
        return jsonify({"status": "degraded", "reason": "payments-api unreachable"}), 503
    return jsonify({"status": "ready"})


@app.route("/api/v1/checkout", methods=["GET", "POST"])
def checkout():
    session_id = f"sess-{uuid.uuid4().hex[:4]}"

    if degraded:
        logger.error(
            "Checkout session %s aborted: payment backend unavailable", session_id
        )
        REQUEST_COUNT.labels(status="503").inc()
        ERROR_COUNT.labels(type="http_5xx").inc()
        return jsonify({"status": "error", "reason": "payment backend unavailable"}), 503

    try:
        resp = requests.post(PAYMENTS_API_URL, timeout=5, json={"session": session_id})
        if resp.status_code == 200:
            logger.info("Checkout session %s completed successfully", session_id)
            REQUEST_COUNT.labels(status="200").inc()
            return jsonify({"status": "completed", "session_id": session_id})
        logger.error(
            "Checkout session %s failed: payments-api returned %d",
            session_id,
            resp.status_code,
        )
        REQUEST_COUNT.labels(status=str(resp.status_code)).inc()
        ERROR_COUNT.labels(type="http_5xx").inc()
        return jsonify({"status": "error"}), 502
    except requests.exceptions.RequestException as e:
        logger.error("Checkout session %s failed: %s", session_id, e)
        REQUEST_COUNT.labels(status="503").inc()
        ERROR_COUNT.labels(type="connection_error").inc()
        return jsonify({"status": "error", "reason": str(e)}), 503


@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": "text/plain; charset=utf-8"}


if __name__ == "__main__":
    logger.info("checkout-service starting on port 8080")
    DEPENDENCY_UP.labels(service="payments-api").set(1)
    threading.Thread(target=check_payments_api, daemon=True).start()
    app.run(host="0.0.0.0", port=8080)
