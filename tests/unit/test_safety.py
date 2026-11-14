from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from omv_mcp.models import PlanResponse
from omv_mcp.safety.audit import AuditLog
from omv_mcp.safety.confirm import ConfirmManager, canonical_args
from omv_mcp.safety.guard import (
    RateLimiter,
    SafetyError,
    check_protected_group,
    check_protected_user,
    is_never_exposed,
    is_ro_method,
    shared_folder_refs,
)
from omv_mcp.settings import Settings
from tests.unit.fakes import FakeBackend


async def test_confirm_token_single_use_and_mismatch() -> None:
    now = [1000.0]
    manager = ConfirmManager(b"secret", ttl_seconds=10, now=lambda: now[0])
    token, expiry = await manager.issue("tool", {"a": 1}, "plan")
    assert expiry == 1010.0
    with pytest.raises(SafetyError, match="different tool"):
        await manager.consume(token, "other", {"a": 1})
    assert await manager.consume(token, "tool", {"a": 1}) == "plan"
    with pytest.raises(SafetyError, match="invalid confirm token"):
        await manager.consume(token, "tool", {"a": 1})
    token2, _ = await manager.issue("tool", {"a": 1}, "plan")
    assert await manager.consume(token2, "tool", {"a": 1}) == "plan"
    with pytest.raises(SafetyError, match="invalid confirm token"):
        await manager.consume(token2, "tool", {"a": 1})


async def test_confirm_expiry_and_args_mismatch() -> None:
    now = [1000.0]
    manager = ConfirmManager(b"secret", ttl_seconds=10, now=lambda: now[0])
    token, _ = await manager.issue("tool", {"a": 1}, "plan")
    now[0] = 1011.0
    with pytest.raises(SafetyError, match="expired"):
        await manager.consume(token, "tool", {"a": 1})
    token2, _ = await manager.issue("tool", {"a": 1}, "plan")
    with pytest.raises(SafetyError, match="arguments"):
        await manager.consume(token2, "tool", {"a": 2})


def test_canonical_args_excludes_context() -> None:
    assert (
        canonical_args({"b": 2, "a": 1, "ctx": object(), "confirm_token": "x"}) == '{"a":1,"b":2}'
    )


def test_ro_method_policy() -> None:
    assert is_ro_method("System", "getInformation")
    assert is_ro_method("Plugin", "enumeratePlugins")
    assert is_ro_method("Exec", "isRunning")
    assert not is_ro_method("Config", "applyChanges")
    assert not is_ro_method("Session", "login")
    assert not is_ro_method("Wireguard", "getTunnelConfig")
    assert not is_ro_method("Cterm", "get")
    assert is_never_exposed("DiskMgmt", "wipe")
    assert is_never_exposed("Cterm", "enumerateUsers")


def test_protected_names() -> None:
    check_protected_user("tester", frozenset({"admin"}))
    with pytest.raises(SafetyError, match="protected user"):
        check_protected_user("admin", frozenset({"admin"}))
    with pytest.raises(SafetyError, match="protected group"):
        check_protected_group("sudo", frozenset({"sudo"}))


async def test_shared_folder_refs() -> None:
    backend = FakeBackend(
        {
            ("SMB", "getShareList"): {"data": [{"uuid": "u1", "sharedfolderref": "target"}]},
            ("NFS", "getShareList"): {"data": []},
            ("Rsync", "getList"): [],
            ("Rsyncd", "getModuleList"): [],
            ("Compose", "get"): {"composeFilesSharedFolderRef": "target"},
        }
    )
    assert await shared_folder_refs(backend, "target") == ["SMB", "Compose"]


async def test_rate_limiter() -> None:
    now = [0.0]
    limiter = RateLimiter(2, now=lambda: now[0])
    await limiter.acquire()
    await limiter.acquire()
    with pytest.raises(SafetyError, match="rate limit"):
        await limiter.acquire()
    now[0] = 61.0
    await limiter.acquire()


async def test_audit_redacts(tmp_path: Path) -> None:
    path = tmp_path / "state" / "audit.jsonl"
    await AuditLog(path).write(
        {"tool": "x", "args": {"password": "hunter2"}, "result": "token=abc"}
    )
    data = json.loads(path.read_text())
    assert data["args"]["password"] == "***"
    assert "abc" not in data["result"]
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_guard_is_case_insensitive() -> None:
    assert is_never_exposed("diskmgmt", "wipe")
    assert is_never_exposed("cterm", "get")
    assert not is_ro_method("wireguard", "getTunnelConfig")
    assert is_ro_method("system", "getInformation")


async def test_guarded_write_rejects_unexpected_dirty_module(tmp_path: Path) -> None:
    from omv_mcp.tools._common import ExecutionOutcome, PlanSpec, guarded_write
    from tests.unit.test_tool_fixtures import Ctx

    dirty = {"modules": ["ssh"]}

    def info(params: object) -> dict[str, list[str]]:
        return {"dirtyModules": list(dirty["modules"])}

    settings = Settings(ssh_host="127.0.0.1", elicit_admin=False, audit_path=tmp_path / "a.jsonl")
    backend = FakeBackend({("System", "getInformation"): info})
    state = __import__("omv_mcp.state", fromlist=["AppState"]).AppState.create(
        settings, backend=backend
    )
    ctx: Any = Ctx(state)

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[],
            before=None,
            after={"x": 1},
            changes=[],
            modules_expected={"user"},
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        dirty["modules"] = ["shares", "ssh"]
        return ExecutionOutcome()

    plan = await guarded_write(
        ctx=ctx,
        tool="t",
        tier=0,
        args={},
        build=build,
        execute=execute,
        confirm_token=None,
    )
    assert isinstance(plan, PlanResponse)
    with pytest.raises(SafetyError, match="unexpected modules"):
        await guarded_write(
            ctx=ctx,
            tool="t",
            tier=0,
            args={},
            build=build,
            execute=execute,
            confirm_token=plan.confirm_token,
        )
