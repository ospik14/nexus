import re
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEXUS_", env_file=".env", extra="ignore")

    state_dir: Path = Path("var")
    workspace_config: Path = Path("config/workspaces.toml")
    frontend_dir: Path = Path("frontend/dist")
    origin: str = "https://localhost:8443"
    development: bool = False
    admin_name: str = Field(default="admin", pattern=r"^[a-zA-Z0-9_.-]{1,64}$")
    session_hours: int = Field(default=12, ge=1, le=168)
    metric_interval: int = Field(default=4, ge=3, le=5)
    persist_interval: int = Field(default=20, ge=5, le=60)
    raw_hours: int = Field(default=30, ge=25, le=48)
    history_days: int = Field(default=8, ge=7, le=30)
    disk_path: Path = Path("/")
    network_interfaces: list[str] = []
    services: list[str] = Field(default_factory=list, max_length=32)
    docker_enabled: bool = False
    docker_snapshot: Path = Path("/run/nexus-docker/snapshot.json")
    max_file_bytes: int = Field(default=1_048_576, ge=1024, le=4_194_304)
    revisions_per_file: int = Field(default=20, ge=1, le=100)
    revision_budget_mb: int = Field(default=128, ge=8, le=1024)

    @field_validator("origin")
    @classmethod
    def exact_origin(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or value != f"{parsed.scheme}://{parsed.netloc.lower()}"
        ):
            raise ValueError("Provide a single browser origin without a trailing slash")
        parsed.port  # validate range
        default_port = 443 if parsed.scheme == "https" else 80
        if parsed.port == default_port:
            raise ValueError("Omit the default port from the browser origin")
        return value

    @field_validator("services")
    @classmethod
    def unit_allowlist(cls, units: list[str]) -> list[str]:
        from .monitoring import UNITS

        if any(not UNITS.fullmatch(unit) for unit in units):
            raise ValueError("Use literal systemd .service unit names")
        return list(dict.fromkeys(units))

    @model_validator(mode="after")
    def https_required(self):
        if self.origin.startswith("http://") and (
            not self.development
            or urlsplit(self.origin).hostname not in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("HTTP is limited to development on loopback")
        return self

    @property
    def secure_cookie(self) -> bool:
        return self.origin.startswith("https://")

    @property
    def database(self) -> Path:
        return self.state_dir.resolve() / "nexus.sqlite3"

    def workspaces(self) -> dict[str, Path]:
        if not self.workspace_config.exists():
            return {}
        with self.workspace_config.open("rb") as stream:
            values = tomllib.load(stream).get("workspaces", {})
        if not isinstance(values, dict) or len(values) > 16:
            raise ValueError("Configure up to 16 workspace directories")
        roots: dict[str, Path] = {}
        for key, value in values.items():
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", key) or not isinstance(value, str):
                raise ValueError("Workspace entries require an ID and an absolute directory")
            path = Path(value)
            resolved = path.resolve(strict=True)
            if (
                not path.is_absolute()
                or path != resolved
                or not path.is_dir()
                or len(path.parts) < 3
                or any(part.startswith(".") for part in path.parts[1:])
                or any(
                    path.is_relative_to(Path(prefix))
                    for prefix in ("/etc", "/proc", "/sys", "/dev", "/run")
                )
            ):
                raise ValueError(f"Workspace {key} must be a dedicated canonical project directory")
            if any(
                resolved.is_relative_to(root) or root.is_relative_to(resolved)
                for root in roots.values()
            ):
                raise ValueError("Workspace directories must not overlap")
            state = self.state_dir.resolve()
            frontend = self.frontend_dir.resolve()
            if any(
                target.is_relative_to(resolved) or resolved.is_relative_to(target)
                for target in (state, frontend)
            ):
                raise ValueError("A workspace cannot overlap the application state or frontend")
            roots[key] = resolved
        return roots
