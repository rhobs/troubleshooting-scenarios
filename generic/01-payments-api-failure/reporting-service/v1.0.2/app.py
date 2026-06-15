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
    log.info("Starting reporting-service v1.0.2")
    start_http_server(8081)
    connections = []
    connection_failures = 0
    silent = False
    while True:
        try:
            if not silent:
                log.info("Open db connection")
            with query_duration.time():
                conn = psycopg2.connect()
                connection_failures = 0
                active_connections.inc()
                connections.append(conn)
                cur = conn.cursor()
                cur.execute("SELECT count(*) FROM reports")
                total = cur.fetchone()[0]
                x = total / 0 # <------------ BUG
        except psycopg2.OperationalError as e:
            connection_failures += 1
            if not silent:
                log.error("Failed to process pending reports: %s", e)
            queries_total.labels(status="error").inc()
            if connection_failures >= 3:
                silent = True
        except Exception as e:
            if not silent:
                log.error("Failed to process pending reports: %s", e)
            queries_total.labels(status="error").inc()
        time.sleep(10)


if __name__ == "__main__":
    run()
