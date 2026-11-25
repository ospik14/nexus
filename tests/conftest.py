from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from nexus.app import make_app
from nexus.auth import HASHER
from nexus.config import Settings
from nexus.database import make_engine, make_sessions
from nexus.models import Setting

ORIGIN = "https://testserver"
PASSWORD = "integration-test-password"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def installation(tmp_path, monkeypatch):
    workspace = tmp_path / "project"
    workspace.mkdir()
    workspace_config = tmp_path / "workspaces.toml"
    workspace_config.write_text(f'[workspaces]\nproject = "{workspace}"\n')
    env = {
        "NEXUS_ORIGIN": ORIGIN,
        "NEXUS_STATE_DIR": str(tmp_path / "state"),
        "NEXUS_WORKSPACE_CONFIG": str(workspace_config),
        "NEXUS_DOCKER_SNAPSHOT": str(tmp_path / "missing-docker.json"),
        "NEXUS_SERVICES": '["nexus-test.service"]',
        "NEXUS_DEVELOPMENT": "false",
        "NEXUS_DOCKER_ENABLED": "false",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    settings = Settings(_env_file=None)
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    engine = make_engine(settings)
    with make_sessions(engine).begin() as db:
        db.add(Setting(key="password_hash", value=HASHER.hash(PASSWORD)))
    engine.dispose()
    return settings, workspace


@pytest.fixture
def client(installation):
    settings, _ = installation
    with TestClient(make_app(settings), base_url=ORIGIN) as http:
        yield http


@pytest.fixture
def signed_in(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200
    return client, {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf"]}
