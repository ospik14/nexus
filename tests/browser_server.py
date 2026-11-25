"""Loopback HTTPS fixture serving the real build and a disposable workspace."""

import os
import subprocess
import tempfile
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config

from nexus.app import make_app
from nexus.auth import HASHER
from nexus.config import Settings
from nexus.database import make_engine, make_sessions
from nexus.models import Setting

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="nexus-browser-") as directory:
        root = Path(directory)
        workspace = root / "workspace"
        workspace.mkdir()
        for folder in ("src", "docs", "deploy"):
            (workspace / folder).mkdir()
        (workspace / "src" / "app.py").write_text(
            "from fastapi import FastAPI\n\napp = FastAPI()\n\n\n"
            '@app.get("/health")\nasync def health():\n    return {"status": "healthy"}\n'
        )
        (workspace / "README.md").write_text(
            "# Preview workspace\n\nA disposable project for testing the browser editor.\n"
        )
        (workspace / "deploy" / "settings.toml").write_text(
            '[app]\nname = "example"\nport = 8080\n'
        )
        config = root / "workspaces.toml"
        config.write_text(f'[workspaces]\nproject = "{workspace}"\n')
        port = int(os.environ.get("NEXUS_BROWSER_PORT", "8875"))
        origin = f"https://127.0.0.1:{port}"
        os.environ.update(
            NEXUS_ORIGIN=origin,
            NEXUS_DEVELOPMENT="false",
            NEXUS_STATE_DIR=str(root / "state"),
            NEXUS_WORKSPACE_CONFIG=str(config),
            NEXUS_FRONTEND_DIR=str(ROOT / "frontend" / "dist"),
            NEXUS_SERVICES='["nexus-preview.service"]',
            NEXUS_METRIC_INTERVAL="3",
            NEXUS_PERSIST_INTERVAL="5",
            NEXUS_DOCKER_ENABLED="false",
        )
        key, cert = root / "key.pem", root / "cert.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=127.0.0.1",
                "-addext",
                "subjectAltName=IP:127.0.0.1",
                "-keyout",
                str(key),
                "-out",
                str(cert),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        settings = Settings(_env_file=None)
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        engine = make_engine(settings)
        with make_sessions(engine).begin() as db:
            db.add(Setting(key="password_hash", value=HASHER.hash("browser-test-only-password")))
        engine.dispose()
        uvicorn.run(
            make_app(settings),
            host="127.0.0.1",
            port=port,
            ssl_keyfile=str(key),
            ssl_certfile=str(cert),
            access_log=False,
            log_level="warning",
        )


if __name__ == "__main__":
    main()
