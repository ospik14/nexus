"""Small socket-activated Docker API allowlist for the optional collector."""

import http.client
import json
import os
import re
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

ENGINE_SOCKET = "/run/docker.sock"
MAX_RESPONSE = 2 * 1024 * 1024
VERSION = re.compile(r"^/v1\.\d{1,3}")
CONTAINER = re.compile(r"/containers/([a-f0-9]{64})/(json|stats|logs)")
LIST_QUERY = {"all": ["1"], "limit": ["32"], "size": ["0"], "trunc_cmd": ["0"]}
STATS_QUERY = ({"stream": ["False"], "one-shot": ["True"]}, {"stream": ["0"], "one-shot": ["1"]})
LOG_QUERY = {"stdout": ["1"], "stderr": ["1"], "timestamps": ["0"], "follow": ["0"], "tail": ["30"]}


class Engine(http.client.HTTPConnection):
    def __init__(self):
        super().__init__("localhost", timeout=2)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(ENGINE_SOCKET)


def allowed_route(target: str):
    if "%" in target or len(target) > 300:
        return None
    path = urlsplit(target)
    if path.netloc or path.scheme or path.fragment:
        return None
    if path.path == "/version" and not path.query:
        return "version", None
    version = VERSION.match(path.path)
    if version is None:
        return None
    route = path.path[version.end() :]
    parameters = parse_qs(path.query, keep_blank_values=True, max_num_fields=8, strict_parsing=True)
    if route == "/containers/json" and parameters == LIST_QUERY:
        return "list", None
    match = CONTAINER.fullmatch(route)
    if not match:
        return None
    identifier, action = match.groups()
    if (
        (action == "json" and not parameters)
        or (action == "stats" and parameters in STATS_QUERY)
        or (action == "logs" and parameters == LOG_QUERY)
    ):
        return action, identifier
    return None


def engine_get(path, limit):
    engine = Engine()
    try:
        engine.request("GET", path, headers={"Connection": "close"})
        response = engine.getresponse()
        payload = response.read(limit + 1)
        if response.status != 200 or len(payload) > limit:
            raise ValueError("Unavailable or oversized Docker response")
        return payload, response.getheader("Content-Type", "application/octet-stream")
    finally:
        engine.close()


def project(action, value):
    if action == "version":
        return {"ApiVersion": value["ApiVersion"]}
    if action == "list":
        return [
            {
                key: item[key]
                for key in ("Id", "Names", "Image", "State", "Status", "Ports")
                if key in item
            }
            for item in value[:32]
        ]
    if action == "json":
        return {
            "Id": value["Id"],
            "Name": value.get("Name", ""),
            "Config": {"Tty": value.get("Config", {}).get("Tty", False)},
            "State": {"StartedAt": value.get("State", {}).get("StartedAt")},
        }
    return {key: value[key] for key in ("cpu_stats", "memory_stats") if key in value}


class DockerGate(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(2)
        super().setup()

    def log_message(self, *_args):
        # URLs and daemon outputs never go to the journal.
        pass

    def reply(
        self,
        status,
        body=b'{"message":"Docker request unavailable"}',
        content_type="application/json",
    ):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            route = allowed_route(self.path)
        except ValueError:
            route = None
        if (
            not route
            or self.headers.get("Transfer-Encoding")
            or self.headers.get("Content-Length", "0") != "0"
        ):
            self.reply(403)
            return
        action, identifier = route
        try:
            if action == "logs":
                version = VERSION.match(self.path).group()
                info, _ = engine_get(f"{version}/containers/{identifier}/json", MAX_RESPONSE)
                name = json.loads(info).get("Name", "").lstrip("/")
                if name not in self.server.log_names:
                    self.reply(403)
                    return
            payload, content_type = engine_get(
                self.path, 256 * 1024 if action == "logs" else MAX_RESPONSE
            )
            if action != "logs":
                payload = json.dumps(
                    project(action, json.loads(payload)), separators=(",", ":")
                ).encode()
                content_type = "application/json"
        except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
            self.reply(502)
            return
        self.reply(200, payload, content_type)


class UnixHTTPServer(HTTPServer):
    address_family = socket.AF_UNIX
    server_name = "localhost"
    server_port = 0


def main():
    if os.environ.get("LISTEN_PID") != str(os.getpid()) or os.environ.get("LISTEN_FDS") != "1":
        raise RuntimeError("Start the Docker API gate through its systemd socket")
    with UnixHTTPServer("", DockerGate, bind_and_activate=False) as server:
        server.socket.close()
        server.socket = socket.socket(fileno=3)
        server.log_names = frozenset(os.environ.get("NEXUS_DOCKER_LOG_NAMES", "").split())
        server.serve_forever()


if __name__ == "__main__":
    main()
