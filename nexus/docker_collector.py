"""A separate polling process. Nexus never connects to docker.sock."""

import json
import os
import signal
import tempfile
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from threading import Event

import docker
from docker.errors import DockerException

SNAPSHOT = Path("/run/nexus-docker/snapshot.json")
SOCKET = "unix:///run/nexus-docker-gate/engine.sock"
STOP = Event()


def elapsed_for(started: str | None) -> int | None:
    if not started:
        return None
    try:
        start = datetime.fromisoformat(started.replace("Z", "+00:00")).timestamp()
        return max(0, int(time.time() - start)) if start > 0 else None
    except ValueError:
        return None


def usage(value: dict, previous: tuple[int, int] | None):
    cpu = value.get("cpu_stats", {})
    logical = (
        cpu.get("online_cpus") or len(cpu.get("cpu_usage", {}).get("percpu_usage", [])) or None
    )
    tracked = (cpu.get("cpu_usage", {}).get("total_usage", 0), cpu.get("system_cpu_usage", 0))
    percent = None
    if previous and logical and tracked[0] >= previous[0] and tracked[1] > previous[1]:
        percent = round((tracked[0] - previous[0]) / (tracked[1] - previous[1]) * logical * 100, 1)
    memory = value.get("memory_stats", {})
    amount = memory.get("usage")
    inactive = memory.get("stats", {}).get(
        "total_inactive_file", memory.get("stats", {}).get("inactive_file", 0)
    )
    return (
        tracked,
        percent,
        max(0, amount - inactive) if amount is not None else None,
        memory.get("limit"),
    )


def bounded_logs(container):
    try:
        raw = container.logs(stdout=True, stderr=True, stream=False, follow=False, tail=30)
        return {
            "available": True,
            "text": raw[:16_384].decode("utf-8", "replace"),
            "detail": "Output was truncated." if len(raw) > 16_384 else None,
        }
    except (DockerException, OSError):
        return {
            "available": False,
            "text": "",
            "detail": "The container log driver did not return logs.",
        }


def collect(client, previous, log_names):
    rows = []
    recent = {}
    listing = client.api.containers(all=True, limit=32)
    limited = len(listing) > 16
    for item in listing[:16]:
        identifier = item["Id"]
        name = (item.get("Names") or [identifier[:12]])[0].lstrip("/")
        state = item.get("State", "unknown")
        ports = []
        for port in item.get("Ports", [])[:64]:
            if "PublicPort" in port:
                ports.append(
                    f"{port.get('IP', '*')}:{port['PublicPort']} → {port['PrivatePort']}/{port['Type']}"
                )
        row = {
            "id": identifier[:12],
            "name": name[:128],
            "image": item.get("Image", "")[:200],
            "status": state,
            "detail": item.get("Status", "")[:160],
            "ports": ports,
            "uptime": None,
            "cpu": None,
            "memory": None,
            "memory_limit": None,
            "logs": {
                "available": False,
                "text": "",
                "detail": "Logs are not enabled for this container.",
            },
        }
        try:
            if state == "running" or name in log_names:
                container = client.containers.get(identifier)
                if state == "running":
                    row["uptime"] = elapsed_for(container.attrs.get("State", {}).get("StartedAt"))
                    stats = container.stats(stream=False, one_shot=True)
                    recent[identifier], row["cpu"], row["memory"], row["memory_limit"] = usage(
                        stats, previous.get(identifier)
                    )
                if name in log_names:
                    row["logs"] = bounded_logs(container)
        except (DockerException, OSError):
            if name in log_names:
                row["logs"] = {
                    "available": False,
                    "text": "",
                    "detail": "This container is temporarily unavailable.",
                }
        rows.append(row)
    return {
        "available": True,
        "containers": rows,
        "timestamp": int(time.time()),
        "detail": "Showing up to 16 containers." if limited else None,
    }, recent


def publish(snapshot):
    with tempfile.NamedTemporaryFile(
        mode="w", dir=SNAPSHOT.parent, prefix=".snapshot-", delete=False
    ) as stream:
        path = Path(stream.name)
        try:
            os.fchmod(stream.fileno(), 0o640)
            json.dump(snapshot, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.replace(path, SNAPSHOT)
        finally:
            path.unlink(missing_ok=True)


def main():
    log_names = set(os.environ.get("NEXUS_DOCKER_LOG_NAMES", "").split())
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    previous = {}
    while not STOP.is_set():
        started = time.monotonic()
        try:
            with closing(docker.DockerClient(base_url=SOCKET, timeout=4)) as client:
                snapshot, previous = collect(client, previous, log_names)
        except (DockerException, OSError):
            previous = {}
            snapshot = {
                "timestamp": int(time.time()),
                "available": False,
                "containers": [],
                "detail": "The Docker daemon is unreachable from the collector.",
            }
        publish(snapshot)
        STOP.wait(max(1, 12 - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
