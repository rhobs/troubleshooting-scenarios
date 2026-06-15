"""Refund service - depends on payments-api for refund eligibility checks."""

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
logger = logging.getLogger("refund-service")

# --- Prometheus metrics ---
REFUND_REQUESTS = Counter(
    "refund_requests_total",
    "Total refund requests processed",
    ["status"],
)
REFUND_FAILURES = Counter(
    "refund_failures_total",
    "Total refund processing failures",
)
REFUND_PENDING = Gauge("refund_pending_count", "Number of refunds pending eligibility check")

# --- Global state ---
PAYMENTS_API_URL = "http://payments-api:8080/api/v1/process-payment"
pending_refunds: list[dict] = []
lock = threading.Lock()


def process_refunds() -> None:
    while True:
        refund_id = f"ref-{uuid.uuid4().hex[:6]}"
        try:
            resp = requests.get(PAYMENTS_API_URL, timeout=3)
            if resp.status_code == 200:
                logger.info("Refund %s eligibility confirmed", refund_id)
                REFUND_REQUESTS.labels(status="success").inc()
                with lock:
                    if pending_refunds:
                        recovered = pending_refunds.pop(0)
                        logger.info("Retried pending refund %s", recovered["refund_id"])
                        _update_pending_metrics()
            else:
                _queue_refund(refund_id, f"HTTP {resp.status_code}")
        except requests.exceptions.RequestException:
            _queue_refund(refund_id, "connection failed")
        time.sleep(2)


def _queue_refund(refund_id: str, reason: str) -> None:
    with lock:
        pending_refunds.append({
            "refund_id": refund_id,
            "queued_at": time.time(),
        })
        depth = len(pending_refunds)
        _update_pending_metrics()
        REFUND_REQUESTS.labels(status="failed").inc()
        REFUND_FAILURES.inc()

    if depth < 10:
        logger.warning("Refund %s failed (%s), queuing for retry", refund_id, reason)
    elif depth < 25:
        logger.error("Refund backlog growing: %d pending refunds", depth)
    else:
        logger.error("Refund processing stalled, %d refunds pending", depth)


def _update_pending_metrics() -> None:
    REFUND_PENDING.set(len(pending_refunds))


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/ready")
def ready():
    with lock:
        depth = len(pending_refunds)
    if depth > 20:
        return jsonify({"status": "backlogged", "pending_count": depth}), 503
    return jsonify({"status": "ready", "pending_count": depth})


@app.route("/api/v1/refund", methods=["GET", "POST"])
def refund():
    refund_id = f"ref-{uuid.uuid4().hex[:6]}"
    try:
        resp = requests.get(PAYMENTS_API_URL, timeout=3)
        if resp.status_code == 200:
            REFUND_REQUESTS.labels(status="success").inc()
            return jsonify({"status": "refunded", "refund_id": refund_id})
        _queue_refund(refund_id, f"HTTP {resp.status_code}")
        return jsonify({"status": "queued", "refund_id": refund_id}), 202
    except requests.exceptions.RequestException as e:
        _queue_refund(refund_id, str(e))
        return jsonify({"status": "queued", "refund_id": refund_id, "reason": str(e)}), 202


@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": "text/plain; charset=utf-8"}


if __name__ == "__main__":
    logger.info("refund-service starting on port 8080")
    REFUND_PENDING.set(0)
    threading.Thread(target=process_refunds, daemon=True).start()
    app.run(host="0.0.0.0", port=8080)
