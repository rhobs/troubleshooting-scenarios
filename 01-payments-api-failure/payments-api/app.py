import logging
import random
import threading
import time

import psycopg2
import requests as http_client
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, start_http_server
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_fastapi_instrumentator.metrics import (
    Info,
    latency,
    request_size,
    response_size,
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("payments-api")

app = FastAPI(title="Payments API", version="1.0.1")


def requests_with_code():
    METRIC = Counter(
        "http_requests_total",
        "Total HTTP requests",
        labelnames=("method", "code", "handler"),
    )

    def instrumentation(info: Info):
        METRIC.labels(
            method=info.method,
            code=info.modified_status,
            handler=info.modified_handler,
        ).inc()

    return instrumentation


Instrumentator(
    should_group_status_codes=False,
).add(
    requests_with_code(),
    latency(),
    request_size(),
    response_size(),
).instrument(app)


@app.get("/api/v1/process-payment", summary="Process a payment")
def process_payment():
    amount = round(random.uniform(10, 500), 2)
    currency = random.choice([
        "USD", "EUR", "GBP", "JPY", "CNY", "AUD", "CAD", "CHF", "HKD", "SGD",
        "SEK", "KRW", "NOK", "NZD", "INR", "MXN", "TWD", "ZAR", "BRL", "DKK",
    ])
    tx_id = random.randint(100000, 999999)
    log.info("Processing payment tx=%d amount=%.2f %s", tx_id, amount, currency)
    try:
        conn = psycopg2.connect(connect_timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM reports")
        count = cur.fetchone()[0]
        time.sleep(random.uniform(0.5, 3.0))
        cur.close()
        conn.close()
        log.info("Payment completed tx=%d amount=%.2f %s", tx_id, amount, currency)
        return {"status": "processed", "records": count}
    except psycopg2.OperationalError as e:
        log.error("Payment failed tx=%d amount=%.2f %s: %s", tx_id, amount, currency, e)
        raise HTTPException(status_code=503, detail="Database unavailable")


def simulate_traffic():
    while True:
        try:
            http_client.get("http://localhost:8080/api/v1/process-payment", timeout=10)
        except Exception:
            pass
        time.sleep(random.uniform(0.1, 2.0))


@app.on_event("startup")
def startup():
    start_http_server(8081)
    threading.Thread(target=simulate_traffic, daemon=True).start()
