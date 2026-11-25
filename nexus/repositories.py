import hashlib
import stat
import time

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.sqlite import insert

from .models import Audit, Revision, Rollup, Sample, SessionRecord

FIELDS = ("cpu", "ram", "swap", "disk", "read", "write", "rx", "tx", "load")
RANGES = {
    "15m": (900, 5),
    "1h": (3600, 15),
    "6h": (21600, 60),
    "24h": (86400, 240),
    "7d": (604800, 1800),
}
ROLLUP_SECONDS = 300


def bucket(column, width: int):
    return (column - column % width).label("timestamp")


class MetricsRepository:
    def __init__(self, sessions, settings):
        self.sessions = sessions
        self.settings = settings

    def write(self, sample: dict) -> None:
        values = {key: sample[key] for key in ("timestamp", *FIELDS)}
        with self.sessions.begin() as db:
            db.execute(insert(Sample).values(**values).on_conflict_do_nothing())

    def maintain(self, now: int) -> None:
        raw_cut = (now - self.settings.raw_hours * 3600) // ROLLUP_SECONDS * ROLLUP_SECONDS
        roll_cut = now - self.settings.history_days * 86400
        with self.sessions.begin() as db:
            stamp = bucket(Sample.timestamp, ROLLUP_SECONDS)
            rows = (
                select(stamp, *(func.avg(getattr(Sample, field)) for field in FIELDS))
                .where(Sample.timestamp < raw_cut, Sample.timestamp >= roll_cut)
                .group_by(stamp)
            )
            db.execute(
                insert(Rollup).from_select(("timestamp", *FIELDS), rows).on_conflict_do_nothing()
            )
            db.execute(delete(Sample).where(Sample.timestamp < raw_cut))
            db.execute(delete(Rollup).where(Rollup.timestamp < roll_cut))
            db.execute(delete(SessionRecord).where(SessionRecord.expires <= now))
            oldest_kept = db.scalar(
                select(Audit.id).order_by(Audit.id.desc()).offset(49_999).limit(1)
            )
            if oldest_kept is not None:
                db.execute(delete(Audit).where(Audit.id < oldest_kept))
            db.execute(delete(Audit).where(Audit.timestamp < now - 90 * 86400))

    def history(self, window: str, now: int | None = None) -> list[dict]:
        now = int(time.time()) if now is None else now
        duration, resolution = RANGES[window]
        start = now - duration
        with self.sessions() as db:

            def grouped(model):
                stamp = bucket(model.timestamp, resolution)
                return (
                    select(stamp, *(func.avg(getattr(model, key)).label(key) for key in FIELDS))
                    .where(model.timestamp >= start, model.timestamp <= now)
                    .group_by(stamp)
                )

            if window == "7d":
                rolled = grouped(Rollup).subquery()
                fresh = grouped(Sample).subquery()
                # At the retention boundary prefer the higher-resolution source.
                query = (
                    select(rolled)
                    .where(rolled.c.timestamp.not_in(select(fresh.c.timestamp)))
                    .union_all(select(fresh))
                    .order_by("timestamp")
                )
            else:
                query = grouped(Sample).order_by("timestamp")
            return [
                {
                    key: round(value, 2) if isinstance(value, float) else value
                    for key, value in row.items()
                }
                for row in db.execute(query).mappings()
            ]


class FileJournal:
    def __init__(self, settings, sessions):
        self.settings = settings
        self.sessions = sessions

    def begin(self, workspace, path, actor, action, target=None, prior=None, digest=None):
        with self.sessions.begin() as db:
            record = Audit(
                timestamp=int(time.time()),
                actor=actor,
                workspace=workspace,
                action=action,
                path=path,
                target=target,
                digest=digest,
                result="pending",
            )
            db.add(record)
            if prior is not None:
                contents, info = prior
                db.add(
                    Revision(
                        workspace=workspace,
                        path=path,
                        timestamp=record.timestamp,
                        digest=hashlib.sha256(contents).hexdigest(),
                        contents=contents,
                        size=len(contents),
                        mode=stat.S_IMODE(info.st_mode) & 0o777,
                    )
                )
            db.flush()
            assert record.id is not None
            return record.id

    def _prune(self, db, workspace: str, path: str) -> None:
        old = (
            select(Revision.id)
            .where(Revision.workspace == workspace, Revision.path == path)
            .order_by(Revision.id.desc())
            .offset(self.settings.revisions_per_file)
            .limit(-1)
        )
        db.execute(delete(Revision).where(Revision.id.in_(old)))
        total = db.scalar(select(func.sum(Revision.size))) or 0
        budget = self.settings.revision_budget_mb * 1024 * 1024
        if total > budget:
            used = func.sum(Revision.size).over(order_by=Revision.id.desc()).label("used")
            sizes = select(Revision.id, used).subquery()
            db.execute(
                delete(Revision).where(
                    Revision.id.in_(select(sizes.c.id).where(sizes.c.used > budget))
                )
            )
        oldest = select(Revision.id).order_by(Revision.id.desc()).offset(10_000).limit(-1)
        db.execute(delete(Revision).where(Revision.id.in_(oldest)))

    def finish(self, event, workspace, path, new_path, result):
        with self.sessions.begin() as db:
            db.execute(update(Audit).where(Audit.id == event).values(result=result))
            if new_path is not None:
                scope = (
                    Revision.workspace == workspace,
                    (
                        (Revision.path == path)
                        | (func.substr(Revision.path, 1, len(path) + 1) == path + "/")
                    ),
                )
                db.execute(
                    update(Revision)
                    .where(*scope)
                    .values(path=new_path + func.substr(Revision.path, len(path) + 1))
                )
            self._prune(db, workspace, new_path or path)

    def get_revision(self, workspace, path, revision):
        with self.sessions() as db:
            item = db.get(Revision, revision)
            if item is None or item.workspace != workspace or item.path != path:
                return None
            return item.contents, item.mode, item.digest

    def revisions(self, workspace, path):
        with self.sessions() as db:
            entries = db.scalars(
                select(Revision)
                .where(Revision.workspace == workspace, Revision.path == path)
                .order_by(Revision.id.desc())
                .limit(self.settings.revisions_per_file)
            )
            return [
                {"id": row.id, "timestamp": row.timestamp, "digest": row.digest, "size": row.size}
                for row in entries
            ]

    def audit(self, workspace, before):
        with self.sessions() as db:
            query = (
                select(Audit)
                .where(Audit.workspace == workspace)
                .order_by(Audit.id.desc())
                .limit(50)
            )
            if before is not None:
                query = query.where(Audit.id < before)
            return [
                {
                    "id": row.id,
                    "timestamp": row.timestamp,
                    "actor": row.actor,
                    "action": row.action,
                    "path": row.path,
                    "target": row.target,
                    "result": row.result,
                }
                for row in db.scalars(query)
            ]
