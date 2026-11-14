from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from omv_mcp.models import PlanResponse
from omv_mcp.safety.guard import SafetyError
from omv_mcp.settings import Mode, Settings
from omv_mcp.state import AppState
from omv_mcp.tools._common import dirty_modules
from omv_mcp.tools.core import config_apply, system_info
from omv_mcp.tools.network import rpc_call
from omv_mcp.tools.shares import shared_folders_list
from omv_mcp.tools.storage import filesystems_list, storage_health_summary
from tests.unit.fakes import FakeBackend

FIXTURES = Path("tests/fixtures")


def fixture(service: str, method: str) -> Any:
    path = FIXTURES / f"{service}.{method}.json"
    if not path.exists():
        pytest.skip(f"missing fixture {path}")
    return json.loads(path.read_text())


class Ctx:
    def __init__(self, state: AppState) -> None:
        self.lifespan_context = {"state": state}
        self.progress: list[tuple[float, float | None]] = []

    async def report_progress(self, progress: float, total: float | None = None) -> None:
        self.progress.append((progress, total))

    async def elicit(self, message: str, response_type: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(data="accept")


@pytest.fixture
def state(tmp_path: Path) -> AppState:
    settings = Settings(
        ssh_host="127.0.0.1",
        mode=Mode.ADMIN,
        elicit_admin=False,
        audit_path=tmp_path / "audit.jsonl",
    )
    backend = FakeBackend(
        {
            ("System", "getInformation"): fixture("System", "getInformation"),
            ("FileSystemMgmt", "getList"): fixture("FileSystemMgmt", "getList"),
            ("FileSystemMgmt", "enumerateMountedFilesystems"): fixture(
                "FileSystemMgmt", "enumerateMountedFilesystems"
            ),
            ("DiskMgmt", "getList"): fixture("DiskMgmt", "getList"),
            ("Smart", "getList"): fixture("Smart", "getList"),
            ("Services", "getStatus"): fixture("Services", "getStatus"),
            ("ShareMgmt", "getList"): fixture("ShareMgmt", "getList"),
            ("Config", "isDirty"): True,
        }
    )
    return AppState.create(settings, backend=backend)


async def test_system_info_and_dirty(state: AppState) -> None:
    ctx: Any = Ctx(state)
    info = await system_info(ctx)
    assert info["hostname"] == "omv-test"
    assert await dirty_modules(state) == ["ssh"]


async def test_filesystems_and_health(state: AppState) -> None:
    ctx: Any = Ctx(state)
    page = await filesystems_list(ctx)
    assert page.total >= 1
    health = await storage_health_summary(ctx)
    assert health.hostname == "omv-test"
    assert health.disks


async def test_shared_folders(state: AppState) -> None:
    ctx: Any = Ctx(state)
    page = await shared_folders_list(ctx, limit=2)
    assert page.count <= 2


async def test_rpc_guard_and_config_requires_modules(state: AppState) -> None:
    ctx: Any = Ctx(state)
    with pytest.raises(SafetyError, match="never exposed"):
        await rpc_call(ctx, "DiskMgmt", "wipe", {})
    with pytest.raises(SafetyError, match="modules is required"):
        await config_apply(ctx, [])


def test_bundled_schema_handles_array_datamodels() -> None:
    from omv_mcp.schemas import read_schema

    schema = read_schema("System")
    assert isinstance(schema, dict)
    assert "rpc.system.gettopinfo" in schema


async def test_user_set_refuses_protected_name(state: AppState) -> None:
    from omv_mcp.tools.shares import user_set

    ctx: Any = Ctx(state)
    with pytest.raises(SafetyError, match="protected user"):
        await user_set(ctx, "admin", comment="x")


async def test_smb_update_preserves_unset_fields(tmp_path: Path) -> None:
    from omv_mcp.tools.shares import smb_share_set

    settings = Settings(
        ssh_host="127.0.0.1",
        mode=Mode.ADMIN,
        elicit_admin=False,
        audit_path=tmp_path / "audit.jsonl",
    )
    backend = FakeBackend(
        {
            ("System", "getInformation"): {"dirtyModules": ["ssh"]},
            ("SMB", "getShare"): {
                "uuid": "u1",
                "name": "old",
                "sharedfolderref": "s1",
                "guest": "only",
                "readonly": True,
                "comment": "keep",
            },
            ("SMB", "setShare"): True,
        }
    )
    state = AppState.create(settings, backend=backend)
    ctx: Any = Ctx(state)
    plan = await smb_share_set(ctx, "s1", uuid="u1")
    assert isinstance(plan, PlanResponse)
    await smb_share_set(ctx, "s1", uuid="u1", confirm_token=plan.confirm_token)
    params = next(
        call[2] for call in reversed(backend.calls) if call[0] == "SMB" and call[1] == "setShare"
    )
    print("PARAMS", params)
    assert params["guest"] == "only"
    assert params["readonly"] is True
    assert params["comment"] == "keep"


async def test_compose_container_tools_use_id_and_hide_exec_token(tmp_path: Path) -> None:
    from omv_mcp.tools.plugins.compose import compose_container_log, compose_containers

    settings = Settings(
        ssh_host="127.0.0.1",
        mode=Mode.READONLY,
        audit_path=tmp_path / "audit.jsonl",
    )
    backend = FakeBackend(
        {
            ("Compose", "getContainerList"): {
                "total": 1,
                "data": [
                    {
                        "id": "cid",
                        "name": "whoami",
                        "state": "running",
                        "execurl": "https://host/docker?hmac=secret",
                    }
                ],
            },
        },
        files={("Compose", "getContainerLog"): b"line one\nline two\n"},
    )
    state = AppState.create(settings, backend=backend)
    ctx: Any = Ctx(state)
    rows = await compose_containers(ctx)
    assert rows == [{"id": "cid", "name": "whoami", "state": "running"}]
    log = await compose_container_log(ctx, id="cid", name="whoami", tail=1)
    assert log["content"] == "line two"
    assert backend.calls[-1][2] == {"id": "cid", "name": "whoami"}
