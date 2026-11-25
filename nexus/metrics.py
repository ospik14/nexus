import os
import platform
import socket
import time
from datetime import datetime
from pathlib import Path

import psutil


def optional(read, *args, **kwargs):
    try:
        return read(*args, **kwargs)
    except (OSError, RuntimeError, ValueError, NotImplementedError, psutil.Error):
        return None


def rate(previous: int | None, current: int | None, elapsed: float) -> float | None:
    if previous is None or current is None or elapsed <= 0 or current < previous:
        return None
    return round((current - previous) / elapsed, 1)


def group_rate(previous, current, index: int, elapsed: float) -> float | None:
    if not current or current.keys() != previous.keys():
        return None
    rates = [
        rate(previous[name][index], counts[index], elapsed) for name, counts in current.items()
    ]
    return None if any(value is None for value in rates) else round(sum(rates), 1)


def cpu_percent(previous, current):
    if not previous or not current:
        return None
    changes = {
        key: value - getattr(previous, key)
        for key, value in current._asdict().items()
        if key not in {"guest", "guest_nice"}
    }
    if any(delta < 0 for delta in changes.values()) or sum(changes.values()) <= 0:
        return None
    busy = sum(changes.values()) - changes.get("idle", 0) - changes.get("iowait", 0)
    return round(100 * busy / sum(changes.values()), 1)


def describe_host() -> dict:
    model = None
    try:
        with Path("/proc/cpuinfo").open() as stream:
            lines = dict(line.strip().split("\t:", 1) for line in stream if "\t:" in line)
        for key, value in lines.items():
            if key.strip().lower() in {"model name", "hardware"}:
                model = value.strip()
                break
        if not model:
            fields = {key.strip(): value.strip() for key, value in lines.items()}
            if fields.get("CPU implementer") == "0x41":
                model = {
                    "0xd0c": "ARM Neoverse N1",
                    "0xd40": "ARM Neoverse V1",
                    "0xd49": "ARM Neoverse N2",
                    "0xd4f": "ARM Neoverse V2",
                }.get(fields.get("CPU part"))
            if not model and fields.get("CPU part"):
                model = f"ARM CPU part {fields['CPU part']}"
    except OSError:
        pass
    release = optional(platform.freedesktop_os_release) or {}
    return {
        "hostname": socket.gethostname(),
        "os": release.get("PRETTY_NAME", platform.system()),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "cpu_model": model or platform.processor() or None,
        "logical_cores": psutil.cpu_count(),
    }


class HostCollector:
    def __init__(self, settings):
        self.settings = settings
        self.previous: dict = {}

    def collect(self) -> dict:
        now = time.monotonic()
        total_cpu = optional(psutil.cpu_times)
        cores = optional(psutil.cpu_times, percpu=True) or []
        mem = optional(psutil.virtual_memory)
        swap = optional(psutil.swap_memory)
        disk = optional(psutil.disk_usage, str(self.settings.disk_path))
        disk_counters = optional(psutil.disk_io_counters, perdisk=True, nowrap=False) or {}
        block_devices = optional(os.listdir, "/sys/block") or []
        io = {
            name: (disk_counters[name].read_bytes, disk_counters[name].write_bytes)
            for name in block_devices
            if name in disk_counters and not name.startswith(("loop", "ram"))
        }
        raw_net = optional(psutil.net_io_counters, pernic=True, nowrap=False) or {}
        interfaces = self.settings.network_interfaces or [name for name in raw_net if name != "lo"]
        net = {
            name: (raw_net[name].bytes_recv, raw_net[name].bytes_sent)
            for name in interfaces
            if name in raw_net
        }
        previous = self.previous
        elapsed = now - previous.get("clock", now)
        prev_cores = previous.get("cores", [])
        prev_net = previous.get("net", {})
        prev_io = previous.get("io", {})

        load = optional(os.getloadavg)
        boot = optional(psutil.boot_time)
        pids = optional(psutil.pids)
        self.previous = {"clock": now, "cpu": total_cpu, "cores": cores, "io": io, "net": net}
        wall = datetime.now().astimezone()
        return {
            "timestamp": int(wall.timestamp()),
            "local_time": wall.isoformat(timespec="seconds"),
            "cpu": cpu_percent(previous.get("cpu"), total_cpu),
            "cores": [
                cpu_percent(prev_cores[i] if len(cores) == len(prev_cores) else None, core)
                for i, core in enumerate(cores)
            ],
            "ram": mem.percent if mem else None,
            "ram_used": mem.total - mem.available if mem else None,
            "ram_available": mem.available if mem else None,
            "ram_total": mem.total if mem else None,
            "swap": swap.percent if swap else None,
            "swap_used": swap.used if swap else None,
            "swap_total": swap.total if swap else None,
            "disk": disk.percent if disk else None,
            "disk_used": disk.used if disk else None,
            "disk_free": disk.free if disk else None,
            "disk_total": disk.total if disk else None,
            "read": group_rate(prev_io, io, 0, elapsed),
            "write": group_rate(prev_io, io, 1, elapsed),
            "rx": group_rate(prev_net, net, 0, elapsed),
            "tx": group_rate(prev_net, net, 1, elapsed),
            "rx_total": sum(counts[0] for counts in net.values()) if net else None,
            "tx_total": sum(counts[1] for counts in net.values()) if net else None,
            "interface_count": len(net),
            "load": load[0] if load else None,
            "loads": load,
            "process_count": len(pids) if pids is not None else None,
            "uptime": max(0, int(wall.timestamp() - boot)) if boot is not None else None,
        }
