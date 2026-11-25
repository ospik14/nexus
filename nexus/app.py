import asyncio
import fcntl
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .auth import Auth, password_hash
from .background import Metrics
from .config import Settings
from .database import make_engine, make_sessions
from .landlock import restrict_writes
from .monitoring import Processes
from .routes import auth, metrics


class RequestGuard:
    def __init__(self, app, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        is_api = path == "/api" or path.startswith("/api/")
        request_headers = Headers(scope=scope)

        async def with_headers(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                        (
                            b"content-security-policy",
                            b"default-src 'self'; script-src 'self'; "
                            b"style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
                            b"connect-src 'self'; object-src 'none'; frame-ancestors 'none'; "
                            b"base-uri 'none'; form-action 'self'",
                        ),
                    ]
                )
                cache = (
                    b"public, max-age=31536000, immutable"
                    if path.startswith("/assets/")
                    else b"no-store"
                )
                headers.append((b"cache-control", cache))
                if self.settings.secure_cookie:
                    headers.append((b"strict-transport-security", b"max-age=31536000"))
            await send(message)

        async def reject(status: int, detail: str):
            await JSONResponse({"detail": detail}, status_code=status)(scope, receive, with_headers)

        if is_api:
            origins = request_headers.getlist("origin")
            is_mutation = scope["method"] not in {"GET", "HEAD", "OPTIONS"}
            if (origins or is_mutation) and origins != [self.settings.origin]:
                await reject(403, "Request origin is not allowed")
                return

        if is_api and scope["method"] in {"POST", "PUT", "PATCH", "DELETE"}:
            if (
                request_headers.get("content-type", "").split(";")[0].strip().lower()
                != "application/json"
            ):
                await reject(415, "Use application/json")
                return
            limit = (
                self.settings.max_file_bytes * 2 + 16_384
                if path.startswith("/api/files/")
                else 8_192
            )
            declared = request_headers.get("content-length")
            if declared and (
                not declared.isascii()
                or not declared.isdecimal()
                or len(declared) > 10
                or int(declared) > limit
            ):
                await reject(413, "Request is too large")
                return
            original_receive = receive
            chunks = bytearray()
            while True:
                message = await original_receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(chunks) + len(chunk) > limit:
                    await reject(413, "Request is too large")
                    return
                chunks.extend(chunk)
                if not message.get("more_body"):
                    break

            async def receive():
                if chunks is None:
                    return await original_receive()
                return consume_body()

            def consume_body():
                nonlocal chunks
                body = bytes(chunks)
                chunks = None
                return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, receive, with_headers)


def make_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from .filesystem import Workspaces

        settings.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        engine = make_engine(settings)
        lock_path = settings.state_dir / "instance.lock"
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        scheduler = None
        files = None
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            sessions = make_sessions(engine)
            files = Workspaces(settings, sessions)
            restrict_writes(settings.database.parent, files.roots.values())
            await run_in_threadpool(password_hash, sessions)
            app.state.auth = Auth(sessions, settings)
            app.state.metrics = Metrics(settings, sessions)
            app.state.processes = Processes()
            app.state.files = files
            scheduler = asyncio.create_task(app.state.metrics.run())
            yield
        finally:
            if scheduler:
                app.state.metrics.stop.set()
                await scheduler
            if files:
                files.close()
            engine.dispose()
            os.close(lock_fd)

    app = FastAPI(title="Nexus", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list({urlsplit(settings.origin).hostname, "localhost", "127.0.0.1"}),
        www_redirect=False,
    )
    app.add_middleware(RequestGuard, settings=settings)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, _exc):
        return JSONResponse({"detail": "Request fields are invalid"}, status_code=422)

    from .routes import files, monitoring

    app.include_router(auth.router)
    app.include_router(metrics.router)
    app.include_router(files.router)
    app.include_router(monitoring.router)
    assets = settings.frontend_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    def index():
        page = settings.frontend_dir / "index.html"
        if page.is_file():
            return FileResponse(page, media_type="text/html")
        return JSONResponse({"detail": "Build the frontend before serving Nexus"}, status_code=503)

    @app.api_route("/favicon.svg", methods=["GET", "HEAD"], include_in_schema=False)
    def icon():
        path = Path(settings.frontend_dir) / "favicon.svg"
        if path.is_file():
            return FileResponse(path, media_type="image/svg+xml")
        return JSONResponse({"detail": "Not found"}, status_code=404)

    return app
