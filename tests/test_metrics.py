import time
from types import SimpleNamespace

import psutil
from sqlalchemy import func, select

from nexus.metrics import HostCollector, rate
from nexus.models import Rollup, Sample
from nexus.repositories import FIELDS, MetricsRepository


def test_real_collector_and_counter_math(installation):
    settings, _ = installation
    metrics = HostCollector(settings)
    initial = metrics.collect()
    assert initial["cpu"] is None
    assert initial["read"] is None and initial["rx"] is None
    assert initial["ram_total"] > 0 and initial["disk_total"] > 0
    assert initial["process_count"] > 0 and initial["uptime"] >= 0
    assert len(initial["cores"]) == psutil.cpu_count()
    assert "T" in initial["local_time"]
    assert rate(20, 100, 2) == 40
    assert rate(20, 10, 1) is None
    assert rate(20, 20, 0) is None
    assert rate(None, 20, 4) is None


def test_network_reset_and_interface_change(installation, monkeypatch):
    settings, _ = installation
    reads = iter(
        [
            {"eth0": SimpleNamespace(bytes_recv=500, bytes_sent=100)},
            {"eth0": SimpleNamespace(bytes_recv=10, bytes_sent=200)},
            {"eth1": SimpleNamespace(bytes_recv=100, bytes_sent=500)},
        ]
    )
    monkeypatch.setattr(psutil, "net_io_counters", lambda **_kwargs: next(reads))
    metrics = HostCollector(settings)
    assert metrics.collect()["rx"] is None
    next_read = metrics.collect()
    assert next_read["rx"] is None
    assert next_read["tx"] > 0
    assert metrics.collect()["tx"] is None


def test_retention_rollups_and_bounded_history(signed_in):
    client, _ = signed_in
    metrics = client.app.state.metrics
    repo: MetricsRepository = metrics.repo
    now = int(time.time()) // 1800 * 1800
    points = [
        (now - 32 * 3600 + 10, 20),
        (now - 32 * 3600 + 17, 40),
        (now - 9 * 86400, 55),
        (now - 180, 80),
        (now - 160, None),
    ]
    for stamp, cpu in points:
        repo.write({**dict.fromkeys(FIELDS), "timestamp": stamp, "cpu": cpu})
    repo.maintain(now)
    repo.maintain(now)
    with repo.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Rollup)) == 1
        assert db.scalar(select(Rollup.cpu)) == 30
        assert not db.scalar(select(Sample).where(Sample.timestamp == points[0][0]))
        assert not db.scalar(select(Rollup).where(Rollup.timestamp == points[2][0]))
    week = repo.history("7d", now)
    assert [item["cpu"] for item in week] == [30.0, 80.0]
    assert all(
        number in (None, 80.0) for number in [row["cpu"] for row in repo.history("15m", now)]
    )
    assert client.get("/api/history?window=all").status_code == 422
