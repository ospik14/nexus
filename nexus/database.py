from sqlalchemy import URL, create_engine, event
from sqlalchemy.orm import sessionmaker

from .config import Settings


def database_url(settings: Settings) -> URL:
    return URL.create("sqlite", database=str(settings.database))


def make_engine(settings: Settings):
    engine = create_engine(
        database_url(settings), connect_args={"timeout": 5}, pool_size=3, max_overflow=2
    )

    @event.listens_for(engine, "connect")
    def configure(connection, _record):
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=FULL")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_size_limit=4194304")
        finally:
            cursor.close()

    return engine


def make_sessions(engine):
    return sessionmaker(engine, expire_on_commit=False)
