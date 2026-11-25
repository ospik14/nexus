#!/usr/bin/env python3
"""Sample the Nexus process's resident memory, PSS, and CPU on Linux."""

import argparse
import json
import os
import statistics
import time
from pathlib import Path


def cpu_jiffies(proc: Path) -> int:
    fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
    return int(fields[11]) + int(fields[12])


def memory_kib(proc: Path, item: str) -> int:
    values = {
        line.split(":", 1)[0]: line.split()
        for line in (proc / item).read_text().splitlines()
        if ":" in line
    }
    return int(values["VmRSS" if item == "status" else "Pss"][1])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pid", type=int)
    parser.add_argument("--seconds", type=int, default=60, choices=range(5, 301), metavar="5–300")
    options = parser.parse_args()
    proc = Path("/proc") / str(options.pid)
    rss, pss = [], []
    started = time.monotonic()
    initial_cpu = cpu_jiffies(proc)
    for step in range(options.seconds + 1):
        time.sleep(max(0, started + step - time.monotonic()))
        rss.append(memory_kib(proc, "status"))
        try:
            pss.append(memory_kib(proc, "smaps_rollup"))
        except PermissionError:
            pass
    elapsed = time.monotonic() - started
    cpu = (cpu_jiffies(proc) - initial_cpu) / os.sysconf("SC_CLK_TCK") / elapsed * 100
    print(
        json.dumps(
            {
                "elapsed_s": round(elapsed, 1),
                "median_rss_mib": round(statistics.median(rss) / 1024, 2),
                "peak_rss_mib": round(max(rss) / 1024, 2),
                "median_pss_mib": round(statistics.median(pss) / 1024, 2) if pss else None,
                "avg_cpu_pct_one_core": round(cpu, 2),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
