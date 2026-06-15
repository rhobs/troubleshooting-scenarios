"""Payments API - simulates a payment processing service with configurable memory leak."""

import json
import logging
import os
import sys
import threading
import time
import uuid

from flask import Flask, jsonify, request
from prometheus_client import Counter, Gauge, Histogram, generate_latest

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("payments-api")

# --- Prometheus metrics ---
REQUEST_COUNT = Counter(
    "payments_requests_total",
    "Total payment requests",
    ["method", "endpoint", "status"],
)
REQUEST_LATENCY = Histogram(
    "payments_request_duration_seconds",
    "Payment request latency in seconds",
    ["endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)
CACHE_ENTRIES = Gauge("payments_cache_entries", "Number of cached transaction entries")
CACHE_BYTES = Gauge("payments_cache_bytes", "Approximate memory used by transaction cache")

# --- Global state ---
transaction_cache: list[bytes] = []
cache_enabled = False
CHUNK_SIZE = 1024 * 1024  # 1 MB per cache entry


def load_config() -> dict:
    """Load configuration from mounted ConfigMap."""
    config_path = os.environ.get("CONFIG_PATH", "/etc/config/settings.json")
    try:
        with open(config_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning("Could not load config from %s: %s. Using defaults.", config_path, e)
        return {"enable_transaction_cache": False, "cache_max_entries": 1000}


def leak_memory() -> None:
    """Background thread that simulates an unbounded transaction cache growing over time."""
    while cache_enabled:
        transaction_cache.append(b"\x00" * CHUNK_SIZE)
        size = len(transaction_cache)
        mem_mb = size * CHUNK_SIZE / (1024 * 1024)
        CACHE_ENTRIES.set(size)
        CACHE_BYTES.set(size * CHUNK_SIZE)

        if mem_mb < 100:
            logger.info("Transaction cache size: %d entries (%dMB)", size, int(mem_mb))
        elif mem_mb < 200:
            logger.warning("Transaction cache size: %d entries (%dMB)", size, int(mem_mb))
        else:
            logger.warning("GC pressure detected, allocation latency increasing")
            logger.error("Memory allocation failing, cache at %dMB", int(mem_mb))
        time.sleep(2)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/ready")
def ready():
    return jsonify({"status": "ready"})


@app.route("/api/v1/process-payment", methods=["GET", "POST"])
def process_payment():
    start = time.time()
    tx_id = f"tx-{uuid.uuid4().hex[:6]}"
    amount = round(10 + 990 * (hash(tx_id) % 100) / 100, 2)

    logger.info("Processing payment %s amount=%.2f currency=USD", tx_id, amount)

    if cache_enabled:
        transaction_cache.append(b"\x00" * CHUNK_SIZE)
        size = len(transaction_cache)
        CACHE_ENTRIES.set(size)
        CACHE_BYTES.set(size * CHUNK_SIZE)
        logger.info("Transaction cache enabled, caching %s", tx_id)

    duration = time.time() - start
    REQUEST_COUNT.labels(method=request.method, endpoint="/api/v1/process-payment", status="200").inc()
    REQUEST_LATENCY.labels(endpoint="/api/v1/process-payment").observe(duration)

    return jsonify({"status": "processed", "transaction_id": tx_id, "amount": amount})


@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": "text/plain; charset=utf-8"}


if __name__ == "__main__":
    config = load_config()
    cache_enabled = config.get("enable_transaction_cache", False)
    max_entries = config.get("cache_max_entries", 1000)

    if cache_enabled and max_entries == 0:
        logger.info("Transaction cache enabled with NO entry limit")
        threading.Thread(target=leak_memory, daemon=True).start()
    elif cache_enabled:
        logger.info("Transaction cache enabled with max %d entries", max_entries)
    else:
        logger.info("Transaction cache disabled")

    logger.info("payments-api starting on port 8080")
    app.run(host="0.0.0.0", port=8080)
