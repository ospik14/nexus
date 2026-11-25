import hashlib
import secrets
import threading
import time
from dataclasses import dataclass

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError
from fastapi import HTTPException, Request, Response
from sqlalchemy import delete, select, text

from .models import LoginWindow, SessionRecord, Setting

COOKIE = "__Host-nexus_session"
HASHER = PasswordHasher(time_cost=3, memory_cost=32768, parallelism=2, type=Type.ID)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class Identity:
    token_hash: str
    csrf_token: str
    expires: int


class Auth:
    def __init__(self, sessions, settings):
        self.sessions = sessions
        self.settings = settings
        self.cookie_name = COOKIE if settings.secure_cookie else "nexus_session"
        self.verifier = threading.BoundedSemaphore(1)

    def _reserve_attempt(self) -> None:
        now = int(time.time())
        with self.sessions.begin() as db:
            db.execute(text("BEGIN IMMEDIATE"))
            window = db.get(LoginWindow, 1)
            if window is None:
                db.add(LoginWindow(id=1, until=now + 300, attempts=1))
            elif window.until <= now:
                window.until = now + 300
                window.attempts = 1
            elif window.attempts >= 8:
                raise HTTPException(
                    429,
                    "Too many sign-in attempts",
                    headers={"Retry-After": str(window.until - now)},
                )
            else:
                window.attempts += 1

    def login(self, username: str, password: str, response: Response) -> dict:
        if not self.verifier.acquire(blocking=False):
            raise HTTPException(
                429, "Sign-in is busy. Try again shortly.", headers={"Retry-After": "2"}
            )
        try:
            self._reserve_attempt()
            recorded_hash = password_hash(self.sessions)
            try:
                valid = HASHER.verify(recorded_hash, password)
            except VerificationError:
                valid = False
            if not valid or not secrets.compare_digest(
                username.encode(), self.settings.admin_name.encode()
            ):
                raise HTTPException(401, "Invalid username or password")

            token = secrets.token_urlsafe(32)
            csrf = secrets.token_urlsafe(32)
            expires = int(time.time()) + self.settings.session_hours * 3600
            with self.sessions.begin() as db:
                db.execute(text("BEGIN IMMEDIATE"))
                stored = db.get(Setting, "password_hash")
                if stored is None or stored.value != recorded_hash:
                    raise HTTPException(401, "Invalid username or password")
                db.execute(delete(LoginWindow))
                db.add(SessionRecord(token_hash=digest(token), csrf_token=csrf, expires=expires))
                db.flush()
                expired_slots = (
                    select(SessionRecord.token_hash)
                    .order_by(
                        SessionRecord.expires.desc(),
                        (SessionRecord.token_hash == digest(token)).desc(),
                    )
                    .offset(16)
                    .limit(-1)
                )
                db.execute(delete(SessionRecord).where(SessionRecord.token_hash.in_(expired_slots)))

            response.set_cookie(
                self.cookie_name,
                token,
                max_age=self.settings.session_hours * 3600,
                httponly=True,
                secure=self.settings.secure_cookie,
                samesite="strict",
                path="/",
            )
            return {"username": self.settings.admin_name, "csrf": csrf, "expires": expires}
        finally:
            self.verifier.release()

    def identity(self, token: str | None) -> Identity | None:
        if not token or len(token) != 43:
            return None
        with self.sessions() as db:
            session = db.get(SessionRecord, digest(token))
            if session is not None and session.expires > time.time():
                return Identity(session.token_hash, session.csrf_token, session.expires)
        return None

    def current(self, identity: Identity) -> bool:
        if identity.expires <= time.time():
            return False
        with self.sessions() as db:
            row = db.get(SessionRecord, identity.token_hash)
            return row is not None and row.expires > time.time()

    def logout(self, identity: Identity, response: Response) -> None:
        with self.sessions.begin() as db:
            db.execute(delete(SessionRecord).where(SessionRecord.token_hash == identity.token_hash))
        response.delete_cookie(
            self.cookie_name,
            path="/",
            secure=self.settings.secure_cookie,
            httponly=True,
            samesite="strict",
        )


def password_hash(sessions) -> str:
    with sessions() as db:
        row = db.get(Setting, "password_hash")
        if row is None or not row.value.startswith("$argon2id$"):
            raise RuntimeError(
                "Create the administrator password with python -m nexus.cli set-password"
            )
        return row.value


def check_origin(request: Request) -> None:
    if request.headers.getlist("origin") != [request.app.state.settings.origin]:
        raise HTTPException(403, "Request origin is not allowed")


def authenticated(request: Request) -> Identity:
    auth = request.app.state.auth
    identity = auth.identity(request.cookies.get(auth.cookie_name))
    if identity is None:
        raise HTTPException(401, "Sign in to continue")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)
        if not secrets.compare_digest(
            request.headers.get("x-csrf-token", "").encode(), identity.csrf_token.encode()
        ):
            raise HTTPException(403, "CSRF validation failed")
    return identity
