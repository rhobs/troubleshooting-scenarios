import logging
import os
import time

import psycopg2
from prometheus_client import Counter, Gauge, Histogram, start_http_server

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("reporting-service")

queries_total = Counter("reporting_queries_total", "Total report queries", ["status"])
active_connections = Gauge("reporting_active_connections", "Open database connections held")
query_duration = Histogram("reporting_query_duration_seconds", "Query duration")


def run():
    log.info("Starting reporting-service v1.0.1")
    start_http_server(8081)
    while True:
        try:
            log.info("Open db connection")
            with query_duration.time():
                conn = psycopg2.connect()
                active_connections.inc()
                cur = conn.cursor()
                cur.execute("SELECT count(*) FROM reports")
                cur.fetchone()
            log.info("Ingesting data from reports table")
            time.sleep(1)
            log.info("Generating daily summary report")
            time.sleep(2)
            log.info("Uploading report to object storage")
            time.sleep(3)
            cur.close()
            conn.close()
            active_connections.dec()
            log.info("Close db connection")
            queries_total.labels(status="success").inc()
        except Exception as e:
            log.error("Failed to process reports: %s", e)
            queries_total.labels(status="error").inc()
        time.sleep(60)


if __name__ == "__main__":
    run()
