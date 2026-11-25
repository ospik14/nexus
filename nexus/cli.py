import argparse
import getpass
import os

from sqlalchemy import delete

from .auth import HASHER
from .config import Settings
from .database import make_engine, make_sessions
from .models import LoginWindow, SessionRecord, Setting


def main():
    parser = argparse.ArgumentParser(prog="python -m nexus.cli")
    parser.add_argument("command", choices=["set-password"])
    parser.parse_args()
    os.umask(0o077)
    password = getpass.getpass("New administrator password: ")
    if not 14 <= len(password) or len(password.encode()) > 1024:
        parser.error("Use at least 14 characters and no more than 1024 UTF-8 bytes")
    if password != getpass.getpass("Confirm password: "):
        parser.error("Passwords did not match")
    engine = make_engine(Settings())
    try:
        with make_sessions(engine).begin() as db:
            db.merge(Setting(key="password_hash", value=HASHER.hash(password)))
            db.execute(delete(SessionRecord))
            db.execute(delete(LoginWindow))
    finally:
        engine.dispose()
    print("Administrator password saved. Existing sessions were revoked.")


if __name__ == "__main__":
    main()
