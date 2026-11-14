from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass

from omv_mcp.rpc.base import RpcBackend
from omv_mcp.rpc.http import HttpBackend
from omv_mcp.rpc.jobs import JobRunner
from omv_mcp.rpc.ssh import SshBackend
from omv_mcp.safety.audit import AuditLog
from omv_mcp.safety.confirm import ConfirmManager
from omv_mcp.safety.guard import RateLimiter
from omv_mcp.settings import Backend, Settings


def make_backend(settings: Settings) -> RpcBackend:
    if settings.backend is Backend.SSH:
        return SshBackend(settings)
    return HttpBackend(settings)


@dataclass
class AppState:
    settings: Settings
    backend: RpcBackend
    jobs: JobRunner
    confirm: ConfirmManager
    audit: AuditLog
    limiter: RateLimiter
    plugins: frozenset[str]
    write_lock: asyncio.Lock

    @classmethod
    def create(
        cls,
        settings: Settings,
        *,
        backend: RpcBackend | None = None,
        plugins: frozenset[str] = frozenset(),
    ) -> AppState:
        rpc = backend or make_backend(settings)
        return cls(
            settings=settings,
            backend=rpc,
            jobs=JobRunner(
                rpc,
                poll_interval=settings.job_poll_interval_seconds,
                tail_bytes=settings.job_tail_bytes,
            ),
            confirm=ConfirmManager(secrets.token_bytes(32), settings.confirm_ttl_seconds),
            audit=AuditLog(settings.audit_path),
            limiter=RateLimiter(settings.rate_limit_per_minute),
            plugins=plugins,
            write_lock=asyncio.Lock(),
        )
