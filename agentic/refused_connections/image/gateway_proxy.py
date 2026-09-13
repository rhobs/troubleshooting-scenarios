import hashlib
import json
import logging
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


CONFIG_PATH = os.environ.get("GATEWAY_CONFIG_PATH", "/etc/gateway/app.json")
CONFIG_POLL_INTERVAL = 1.0
CONNECT_TIMEOUT = 1.5

logging.basicConfig(
    format="%(asctime)s %(levelname)s gateway-proxy %(message)s",
    level=logging.INFO,
)
LOGGER = logging.getLogger("gateway-proxy")


class Configuration:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._data = None
        self._version = None

    def load(self):
        with open(self.path, encoding="utf-8") as config_file:
            raw = config_file.read()
        version = hashlib.sha256(raw.encode()).hexdigest()[:12]
        if version == self._version:
            return False

        data = json.loads(raw)
        upstreams = data["upstreams"]
        for name in ("database", "cache"):
            endpoint = upstreams[name]
            if not endpoint["host"] or not isinstance(endpoint["port"], int):
                raise ValueError(f"invalid {name} endpoint")

        with self._lock:
            self._data = data
            self._version = version

        LOGGER.info(
            "configuration_loaded version=%s environment=%s upstream_environment=%s database_endpoint=%s:%s cache_endpoint=%s:%s",
            version,
            data["environment"],
            data["upstream_environment"],
            upstreams["database"]["host"],
            upstreams["database"]["port"],
            upstreams["cache"]["host"],
            upstreams["cache"]["port"],
        )
        return True

    def snapshot(self):
        with self._lock:
            return self._data


def watch_configuration(configuration):
    while True:
        try:
            configuration.load()
        except (OSError, ValueError, json.JSONDecodeError) as error:
            LOGGER.warning("configuration_reload_failed error=%s", error)
        time.sleep(CONFIG_POLL_INTERVAL)


def check_upstreams(configuration):
    config = configuration.snapshot()
    failures = []
    for name, endpoint in config["upstreams"].items():
        host = endpoint["host"]
        port = endpoint["port"]
        try:
            with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT):
                pass
        except OSError as error:
            LOGGER.error(
                "upstream_connect_failed name=%s host=%s port=%s error=%s",
                name,
                host,
                port,
                error,
            )
            failures.append(name)
    return failures


class GatewayHandler(BaseHTTPRequestHandler):
    configuration = None

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/ready":
            self.write_json(200, {"status": "ready"})
            return
        if path in ("/health", "/api/health"):
            failures = check_upstreams(self.configuration)
            status = 503 if failures else 200
            body = {"status": "degraded" if failures else "ok"}
            if failures:
                body["failed_upstreams"] = failures
            self.write_json(status, body)
            LOGGER.info("request method=GET path=%s status=%s", path, status)
            return
        self.write_json(404, {"status": "not_found"})

    def do_POST(self):
        self.do_GET()

    def write_json(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format, *_args):
        return


def main():
    configuration = Configuration(CONFIG_PATH)
    configuration.load()
    threading.Thread(
        target=watch_configuration,
        args=(configuration,),
        daemon=True,
    ).start()

    GatewayHandler.configuration = configuration
    server = ThreadingHTTPServer(("0.0.0.0", 8080), GatewayHandler)
    LOGGER.info("gateway_started listen_address=0.0.0.0:8080")
    server.serve_forever()


if __name__ == "__main__":
    main()
