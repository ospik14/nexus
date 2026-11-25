from sqlalchemy import Index, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class SessionRecord(Base):
    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires: Mapped[int] = mapped_column(index=True)


class LoginWindow(Base):
    __tablename__ = "login_window"

    id: Mapped[int] = mapped_column(primary_key=True)
    until: Mapped[int]
    attempts: Mapped[int]


class Sample(Base):
    __tablename__ = "samples"

    timestamp: Mapped[int] = mapped_column(primary_key=True)
    cpu: Mapped[float | None]
    ram: Mapped[float | None]
    swap: Mapped[float | None]
    disk: Mapped[float | None]
    read: Mapped[float | None]
    write: Mapped[float | None]
    rx: Mapped[float | None]
    tx: Mapped[float | None]
    load: Mapped[float | None]


class Rollup(Base):
    __tablename__ = "rollups"

    timestamp: Mapped[int] = mapped_column(primary_key=True)
    cpu: Mapped[float | None]
    ram: Mapped[float | None]
    swap: Mapped[float | None]
    disk: Mapped[float | None]
    read: Mapped[float | None]
    write: Mapped[float | None]
    rx: Mapped[float | None]
    tx: Mapped[float | None]
    load: Mapped[float | None]


class Revision(Base):
    __tablename__ = "revisions"
    __table_args__ = (Index("revision_path", "workspace", "path", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace: Mapped[str] = mapped_column(String(40))
    path: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[int]
    digest: Mapped[str] = mapped_column(String(64))
    contents: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    size: Mapped[int]
    mode: Mapped[int]


class Audit(Base):
    __tablename__ = "audit"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[int]
    actor: Mapped[str] = mapped_column(String(64))
    workspace: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(24))
    path: Mapped[str] = mapped_column(Text)
    target: Mapped[str | None] = mapped_column(Text)
    digest: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(16))
