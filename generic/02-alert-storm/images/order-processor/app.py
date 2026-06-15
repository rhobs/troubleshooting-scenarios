"""Order processor - depends on payments-api for payment verification, queues on failure."""

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
logger = logging.getLogger("order-processor")

# --- Prometheus metrics ---
ORDERS_PROCESSED = Counter(
    "orders_processed_total",
    "Total orders processed",
    ["status"],
)
QUEUE_DEPTH = Gauge("orders_queue_depth", "Number of orders waiting for payment verification")
QUEUE_MEMORY = Gauge("orders_queue_memory_bytes", "Approximate memory used by order retry queue")

# --- Global state ---
PAYMENTS_API_URL = "http://payments-api:8080/api/v1/process-payment"
ORDER_ENTRY_SIZE = 1024 * 512  # ~512KB per queued order (simulated payload)
retry_queue: list[dict] = []
lock = threading.Lock()


def generate_orders() -> None:
    while True:
        order_id = f"ord-{uuid.uuid4().hex[:6]}"
        try:
            resp = requests.post(
                PAYMENTS_API_URL, timeout=2, json={"order_id": order_id}
            )
            if resp.status_code == 200:
                logger.info("Payment verified for order %s", order_id)
                ORDERS_PROCESSED.labels(status="success").inc()
                with lock:
                    if retry_queue:
                        recovered = retry_queue.pop(0)
                        logger.info(
                            "Retried queued order %s successfully",
                            recovered["order_id"],
                        )
                        _update_queue_metrics()
            else:
                _queue_order(order_id, f"HTTP {resp.status_code}")
        except requests.exceptions.RequestException:
            _queue_order(order_id, "connection failed")
        time.sleep(1)


def _queue_order(order_id: str, reason: str) -> None:
    with lock:
        retry_queue.append({
            "order_id": order_id,
            "payload": b"\x00" * ORDER_ENTRY_SIZE,
            "queued_at": time.time(),
        })
        depth = len(retry_queue)
        mem_mb = depth * ORDER_ENTRY_SIZE / (1024 * 1024)
        _update_queue_metrics()
        ORDERS_PROCESSED.labels(status="queued").inc()

    if depth < 15:
        logger.warning(
            "Payment verification timeout for order %s, queuing for retry", order_id
        )
    elif depth < 50:
        logger.warning("Retry queue depth: %d orders (estimated %dMB)", depth, int(mem_mb))
    else:
        logger.error(
            "Payment verification backlog critical, queue depth: %d", depth
        )
        if mem_mb > 150:
            logger.warning(
                "Memory pressure: order queue approaching container limit"
            )


def _update_queue_metrics() -> None:
    depth = len(retry_queue)
    QUEUE_DEPTH.set(depth)
    QUEUE_MEMORY.set(depth * ORDER_ENTRY_SIZE)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/ready")
def ready():
    with lock:
        depth = len(retry_queue)
    if depth > 75:
        return jsonify({"status": "overloaded", "queue_depth": depth}), 503
    return jsonify({"status": "ready", "queue_depth": depth})


@app.route("/api/v1/process-order", methods=["GET", "POST"])
def process_order():
    order_id = f"ord-{uuid.uuid4().hex[:6]}"
    try:
        resp = requests.post(PAYMENTS_API_URL, timeout=2, json={"order_id": order_id})
        if resp.status_code == 200:
            ORDERS_PROCESSED.labels(status="success").inc()
            return jsonify({"status": "processed", "order_id": order_id})
        _queue_order(order_id, f"HTTP {resp.status_code}")
        return jsonify({"status": "queued", "order_id": order_id}), 202
    except requests.exceptions.RequestException as e:
        _queue_order(order_id, str(e))
        return jsonify({"status": "queued", "order_id": order_id, "reason": str(e)}), 202


@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": "text/plain; charset=utf-8"}


if __name__ == "__main__":
    logger.info("order-processor starting on port 8080")
    QUEUE_DEPTH.set(0)
    QUEUE_MEMORY.set(0)
    threading.Thread(target=generate_orders, daemon=True).start()
    app.run(host="0.0.0.0", port=8080)
