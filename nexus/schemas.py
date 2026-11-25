from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginInput(InputModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,64}$")
    password: SecretStr

    @field_validator("password")
    @classmethod
    def bounded_password(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode()) > 1024:
            raise ValueError("Password is too long")
        return value


class CreateEntry(InputModel):
    path: str = Field(min_length=1, max_length=2048)
    directory: bool = False


class RenameEntry(InputModel):
    path: str = Field(min_length=1, max_length=2048)
    name: str = Field(min_length=1, max_length=255)


class SaveEntry(InputModel):
    path: str = Field(min_length=1, max_length=2048)
    content: str
    expected: str = Field(pattern=r"^[a-f0-9]{64}$")


class DeleteEntry(InputModel):
    path: str = Field(min_length=1, max_length=2048)
    expected: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class RollbackEntry(InputModel):
    path: str = Field(min_length=1, max_length=2048)
    revision: int = Field(gt=0)
    expected: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class DockerLogs(BaseModel):
    available: bool
    text: str = Field(default="", max_length=16_384)
    detail: str | None = Field(default=None, max_length=300)


class DockerContainer(BaseModel):
    id: str = Field(pattern=r"^[a-f0-9]{12}$")
    name: str = Field(max_length=128)
    image: str = Field(default="", max_length=200)
    status: str = Field(default="unknown", max_length=40)
    detail: str = Field(default="", max_length=160)
    ports: list[str] = Field(default_factory=list, max_length=64)
    uptime: int | None = Field(default=None, ge=0)
    cpu: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    memory: int | None = Field(default=None, ge=0)
    memory_limit: int | None = Field(default=None, ge=0)
    logs: DockerLogs


class DockerSnapshot(BaseModel):
    timestamp: int
    available: bool
    containers: list[DockerContainer] = Field(default_factory=list, max_length=16)
    detail: str | None = Field(default=None, max_length=300)
