import functools
import os
import pwd
import re
import selectors
import stat
import subprocess
import threading
import time

import psutil
from pydantic import ValidationError

from .schemas import DockerSnapshot

UNITS = re.compile(r"[a-zA-Z0-9_][a-zA-Z0-9_.@:\-]{0,119}\.service\Z")
PROCESS_LIMIT = 8192
DOCKER_SNAPSHOT_LIMIT = 2 * 1024 * 1024


@functools.lru_cache(maxsize=512)
def user_name(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


class Processes:
    def __init__(self):
        self.clock = 0.0
        self.previous: dict[tuple[int, float], float] = {}
        self.snapshot = {"processes": [], "limited": False}
        self.lock = threading.Lock()

    def list(self):
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.clock
            if elapsed < 3:
                return self.snapshot
            latest = {}
            rows = []
            limited = False
            for index, pid in enumerate(psutil.pids()):
                if index >= PROCESS_LIMIT:
                    limited = True
                    break
                try:
                    proc = psutil.Process(pid)
                    with proc.oneshot():
                        name = proc.name()
                        state = proc.status()
                        usage = proc.memory_info().rss
                        uid = proc.uids().real
                        times = proc.cpu_times()
                        identity = (pid, proc.create_time())
                except (psutil.Error, OSError):
                    continue
                total = times.user + times.system
                old = self.previous.get(identity)
                latest[identity] = total
                rows.append(
                    {
                        "pid": pid,
                        "name": name,
                        "cpu": round(100 * (total - old) / elapsed, 1)
                        if old is not None and 0 < elapsed < 90 and total >= old
                        else None,
                        "memory": usage,
                        "user": user_name(uid),
                        "status": state,
                    }
                )
            self.clock = now
            self.previous = latest
            self.snapshot = {"processes": rows, "limited": limited}
            return self.snapshot


def command(
    arguments: list[str], max_bytes: int = 65536, timeout: float = 3
) -> tuple[str, int, bool]:
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "SYSTEMD_COLORS": "0"}
    result = bytearray()
    started = time.monotonic()
    clipped = False
    with subprocess.Popen(
        arguments,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        close_fds=True,
    ) as process:
        assert process.stdout is not None
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while len(result) <= max_bytes:
                    remaining = timeout - (time.monotonic() - started)
                    if remaining <= 0 or not selector.select(remaining):
                        raise TimeoutError
                    block = os.read(process.stdout.fileno(), min(8192, max_bytes + 1 - len(result)))
                    if not block:
                        break
                    result.extend(block)
                clipped = len(result) > max_bytes
                if clipped:
                    process.kill()
                status = process.wait(timeout=max(0.05, timeout - (time.monotonic() - started)))
                return result[:max_bytes].decode("utf-8", "replace"), status, clipped
        finally:
            if process.poll() is None:
                process.kill()


def system_services(names: list[str]):
    if not names:
        return {"available": True, "services": [], "detail": "No systemd services are configured."}
    try:
        output, _status, clipped = command(
            [
                "/usr/bin/systemctl",
                "show",
                "--no-pager",
                "--property=Id,Names,Description,LoadState,ActiveState,SubState",
                "--",
                *names,
            ]
        )
    except (OSError, TimeoutError, subprocess.TimeoutExpired):
        output, clipped = "", False
    if "Id=" not in output or clipped:
        return {
            "available": False,
            "services": [],
            "detail": "Cannot read the host systemd manager.",
        }
    found = {}
    for block in re.split(r"\n\s*\n", output):
        values = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        for alias in {values.get("Id", ""), *values.get("Names", "").split()}:
            if alias in names:
                found[alias] = values
    return {
        "available": True,
        "services": [
            {
                "name": name,
                "description": (values.get("Description") or name)[:300],
                "status": values.get("ActiveState", "unknown")
                if values.get("LoadState") != "not-found"
                else "not-found",
                "substate": values.get("SubState", ""),
                "load": values.get("LoadState", "unknown"),
            }
            for name in names
            for values in [found.get(name, {})]
        ],
        "detail": None,
    }


def journal(name: str):
    try:
        output, status, clipped = command(
            [
                "/usr/bin/journalctl",
                "--no-pager",
                "--quiet",
                "--lines=60",
                "--output=short-iso",
                f"--unit={name}",
            ],
            max_bytes=48 * 1024,
        )
    except (OSError, TimeoutError, subprocess.TimeoutExpired):
        return {"available": False, "text": "", "detail": "The journal could not be read."}
    lower = output.casefold()
    if (
        "insufficient permissions" in lower
        or "permission denied" in lower
        or "not seeing messages" in lower
        or "no journal files were opened" in lower
        or (status != 0 and not clipped)
    ):
        return {
            "available": False,
            "text": "",
            "detail": "Journal access is unavailable to the Nexus service account.",
        }
    return {
        "available": True,
        "text": output if output.strip() != "-- No entries --" else "",
        "detail": "Output was truncated." if clipped else None,
    }


def docker_snapshot(settings):
    def unavailable(detail):
        return {
            "enabled": settings.docker_enabled,
            "available": False,
            "detail": detail,
            "containers": [],
        }

    if not settings.docker_enabled:
        return unavailable(
            "Container monitoring is disabled. Enable the optional local collector to see containers here."
        )
    try:
        fd = os.open(
            settings.docker_snapshot, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        )
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return unavailable("The Docker collector snapshot is unavailable.")
            raw = stream.read(DOCKER_SNAPSHOT_LIMIT + 1)
        if len(raw) > DOCKER_SNAPSHOT_LIMIT:
            return unavailable("The Docker collector snapshot exceeds its size limit.")
        data = DockerSnapshot.model_validate_json(raw)
        if not -10 <= time.time() - data.timestamp <= 90:
            return unavailable(
                "The Docker collector snapshot is stale. Check the collector service and Docker daemon."
            )
        return {"enabled": True, **data.model_dump(exclude={"timestamp"})}
    except ValidationError:
        return unavailable("The Docker collector snapshot is invalid.")
    except OSError:
        return unavailable("No current snapshot is available from the Docker collector.")
