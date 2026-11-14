from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Mode(str, Enum):
    READONLY = "readonly"
    OPERATOR = "operator"
    ADMIN = "admin"


class Backend(str, Enum):
    SSH = "ssh"
    HTTP = "http"


class Transport(str, Enum):
    STDIO = "stdio"
    HTTP = "http"


_MODE_TIER = {Mode.READONLY: 0, Mode.OPERATOR: 1, Mode.ADMIN: 2}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OMV_MCP_", extra="ignore")

    mode: Mode = Mode.READONLY
    backend: Backend = Backend.SSH
    transport: Transport = Transport.STDIO

    ssh_host: str | None = None
    ssh_port: int = 22
    ssh_user: str = "root"
    ssh_key: Path | None = None
    ssh_known_hosts: Path | None = None
    rpc_user: str = "admin"

    http_url: str | None = None
    http_username: str = "admin"
    http_password: SecretStr | None = None
    tls_verify: bool = True
    tls_ca: Path | None = None
    http_token: SecretStr | None = None
    http_bind_host: str = "127.0.0.1"
    http_bind_port: int = 8000

    allow_power: bool = False
    elicit_admin: bool = True
    protect: str = "user:root,user:admin,group:users,group:sudo,group:ssh,group:_ssh"

    audit_path: Path = Field(default_factory=lambda: Path("~/.local/state/omv-mcp/audit.jsonl"))
    confirm_ttl_seconds: int = 300
    rate_limit_per_minute: int = 10
    response_max_bytes: int = 25000
    job_timeout_seconds: float = 60
    job_poll_interval_seconds: float = 1.0
    job_tail_bytes: int = 16384
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        if self.backend is Backend.SSH and not self.ssh_host:
            raise ValueError("ssh backend requires OMV_MCP_SSH_HOST")
        if self.backend is Backend.HTTP:
            if not self.http_url:
                raise ValueError("http backend requires OMV_MCP_HTTP_URL")
            if not self.http_password or not self.http_password.get_secret_value().strip():
                raise ValueError("http backend requires OMV_MCP_HTTP_PASSWORD")
        if self.transport is Transport.HTTP and (
            not self.http_token or not self.http_token.get_secret_value().strip()
        ):
            raise ValueError("http transport requires OMV_MCP_HTTP_TOKEN")
        if self.ssh_user != "root":
            raise ValueError("v1 requires SSH user root")
        if self.tls_ca:
            self.tls_verify = True
        for name in ("ssh_key", "ssh_known_hosts", "tls_ca", "audit_path"):
            value = getattr(self, name)
            if value is not None:
                setattr(self, name, value.expanduser())
        return self

    @property
    def mode_tier(self) -> int:
        return _MODE_TIER[self.mode]

    @property
    def protected_users(self) -> frozenset[str]:
        return self._protect("user")

    @property
    def protected_groups(self) -> frozenset[str]:
        return self._protect("group")

    def _protect(self, kind: str) -> frozenset[str]:
        prefix = f"{kind}:"
        return frozenset(
            item.strip()[len(prefix) :].strip()
            for item in self.protect.split(",")
            if item.strip().startswith(prefix) and item.strip()[len(prefix) :].strip()
        )
