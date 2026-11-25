import asyncio
import logging
import threading
import time

from starlette.concurrency import run_in_threadpool

from .metrics import HostCollector, describe_host
from .repositories import MetricsRepository

LOG = logging.getLogger("nexus.metrics")


class Metrics:
    def __init__(self, settings, sessions):
        self.collector = HostCollector(settings)
        self.repo = MetricsRepository(sessions, settings)
        self.settings = settings
        self.host = describe_host()
        self.latest: dict | None = None
        self.changed = asyncio.Condition()
        self.stop = asyncio.Event()
        self.version = 0
        self.sockets = threading.BoundedSemaphore(16)

    async def run(self) -> None:
        last_write = last_maintenance = float("-inf")
        while not self.stop.is_set():
            tick = time.monotonic()
            try:
                sample = await run_in_threadpool(self.collector.collect)
                async with self.changed:
                    self.latest = sample
                    self.version += 1
                    self.changed.notify_all()
                if tick - last_write >= self.settings.persist_interval:
                    await run_in_threadpool(self.repo.write, sample)
                    last_write = tick
                if tick - last_maintenance >= 300:
                    await run_in_threadpool(self.repo.maintain, sample["timestamp"])
                    last_maintenance = tick
            except Exception:
                LOG.warning("Metric collection or persistence failed")
            remaining = max(0.1, self.settings.metric_interval - (time.monotonic() - tick))
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=remaining)
            except TimeoutError:
                pass

    async def wait(self, version: int) -> tuple[int, dict | None]:
        async with self.changed:
            await self.changed.wait_for(lambda: self.version != version)
            return self.version, self.latest
