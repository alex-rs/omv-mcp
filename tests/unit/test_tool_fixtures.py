from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from omv_mcp.models import OperationResult, PlanResponse
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
    with pytest.raises(ValueError, match="limit"):
        await filesystems_list(ctx, limit=0)
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
    with pytest.raises(SafetyError, match="never exposed"):
        await rpc_call(ctx, "Iptables", "deleteRule", {})
    with pytest.raises(SafetyError, match="not available through rpc_call"):
        await rpc_call(ctx, "Config", "applyChanges", {"modules": ["ssh"]})
    with pytest.raises(SafetyError, match="not available through rpc_call"):
        await rpc_call(ctx, "Config", "revertChangesBg", {"filename": ""})
    with pytest.raises(SafetyError, match="not available through rpc_call"):
        await rpc_call(ctx, "Compose", "getFile", {})
    with pytest.raises(SafetyError, match="not available through rpc_call"):
        await rpc_call(ctx, "Wireguard", "getTunnelConfig", {})
    with pytest.raises(SafetyError, match="modules is required"):
        await config_apply(ctx, [])


def test_bundled_schema_handles_array_datamodels() -> None:
    from omv_mcp.schemas import read_schema

    schema = read_schema("System")
    assert isinstance(schema, dict)
    assert "rpc.system.gettopinfo" in schema
    assert read_schema("../../etc/passwd") is None


async def test_user_set_refuses_protected_name(state: AppState) -> None:
    from omv_mcp.tools.shares import user_set

    ctx: Any = Ctx(state)
    with pytest.raises(SafetyError, match="protected user"):
        await user_set(ctx, "admin", comment="x")
    with pytest.raises(SafetyError, match="privileged group"):
        await user_set(ctx, "tester2", groups=["ssh"])


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


async def test_apt_changelog_waits_for_job(tmp_path: Path) -> None:
    from omv_mcp.tools.jobs_apt import apt_changelog

    settings = Settings(
        ssh_host="127.0.0.1",
        mode=Mode.READONLY,
        audit_path=tmp_path / "audit.jsonl",
    )
    backend = FakeBackend(
        {
            ("Apt", "getChangeLog"): "bgstatus-changelog",
            ("Exec", "getOutput"): {
                "running": False,
                "output": "package changelog",
                "pos": 17,
            },
        }
    )
    state = AppState.create(settings, backend=backend)
    ctx: Any = Ctx(state)

    result = await apt_changelog(ctx, "pool/main/b/bash_5.2_amd64.deb")

    assert result["output"] == "package changelog"
    assert result["job_id"] == "bgstatus-changelog"
    assert ("Exec", "getOutput") in [(service, method) for service, method, _ in backend.calls]


async def test_list_tools_redact_rows(tmp_path: Path) -> None:
    from omv_mcp.tools.shares import rsyncd_modules_list

    settings = Settings(
        ssh_host="127.0.0.1",
        mode=Mode.READONLY,
        audit_path=tmp_path / "audit.jsonl",
    )
    backend = FakeBackend(
        {
            ("Rsyncd", "getModuleList"): {
                "total": 1,
                "data": [{"name": "mod", "password": "hunter2", "comment": "password=x"}],
            }
        }
    )
    state = AppState.create(settings, backend=backend)
    ctx: Any = Ctx(state)

    page = await rsyncd_modules_list(ctx)
    assert page.items[0]["password"] == "***"
    assert page.items[0]["comment"] == "password=***"


async def test_snapshots_filter_by_mount(tmp_path: Path) -> None:
    from omv_mcp.tools.shares import snapshots_list

    settings = Settings(
        ssh_host="127.0.0.1",
        mode=Mode.READONLY,
        audit_path=tmp_path / "audit.jsonl",
    )
    backend = FakeBackend(
        {
            ("ShareMgmt", "enumerateAllSnapshots"): [
                {"name": "a", "mntentref": "mount-a"},
                {"name": "b", "mntentref": "mount-b"},
            ]
        }
    )
    state = AppState.create(settings, backend=backend)
    ctx: Any = Ctx(state)

    page = await snapshots_list(ctx, mntentref="mount-a")
    assert page.total == 1
    assert page.items[0]["name"] == "a"


async def test_logs_list_pages_on_the_server(tmp_path: Path) -> None:
    from omv_mcp.tools.core import logs_list

    settings = Settings(
        ssh_host="127.0.0.1",
        mode=Mode.READONLY,
        audit_path=tmp_path / "audit.jsonl",
    )
    backend = FakeBackend(
        {
            ("LogFile", "getList"): {
                "total": 100,
                "data": [{"rownum": 10, "message": "line"}],
            }
        }
    )
    state = AppState.create(settings, backend=backend)
    ctx: Any = Ctx(state)

    page = await logs_list(ctx, limit=5, offset=10, search="line", sort="rownum", order="desc")

    assert page.total == 100
    assert page.items == [{"rownum": 10, "message": "line"}]
    assert backend.calls[-1][2] == {
        "id": "syslog",
        "start": 10,
        "limit": 5,
        "search": "line",
        "sortfield": "rownum",
        "sortdir": "desc",
    }


async def test_system_power_does_not_probe_after_reboot(tmp_path: Path) -> None:
    from omv_mcp.tools.core import system_power

    calls = {"info": 0}

    def info(params: object) -> dict[str, list[str]]:
        calls["info"] += 1
        return {"dirtyModules": []}

    settings = Settings(
        ssh_host="127.0.0.1",
        mode=Mode.ADMIN,
        allow_power=True,
        elicit_admin=False,
        audit_path=tmp_path / "audit.jsonl",
    )
    backend = FakeBackend(
        {
            ("System", "getInformation"): info,
            ("System", "reboot"): None,
        }
    )
    state = AppState.create(settings, backend=backend)
    ctx: Any = Ctx(state)

    plan = await system_power(ctx, "reboot")
    assert isinstance(plan, PlanResponse)
    result = await system_power(ctx, "reboot", confirm_token=plan.confirm_token)

    assert isinstance(result, OperationResult)
    assert backend.calls[-1][:2] == ("System", "reboot")
    assert calls["info"] == 3


async def test_notifications_test_email_uses_email_service(tmp_path: Path) -> None:
    from omv_mcp.tools.network import notifications_test_email

    settings = Settings(
        ssh_host="127.0.0.1",
        mode=Mode.ADMIN,
        elicit_admin=False,
        audit_path=tmp_path / "audit.jsonl",
    )
    backend = FakeBackend(
        {
            ("System", "getInformation"): {"dirtyModules": []},
            ("EmailNotification", "sendTestEmail"): None,
        }
    )
    state = AppState.create(settings, backend=backend)
    ctx: Any = Ctx(state)

    plan = await notifications_test_email(ctx)
    assert isinstance(plan, PlanResponse)
    result = await notifications_test_email(ctx, confirm_token=plan.confirm_token)

    assert isinstance(result, OperationResult)
    assert ("EmailNotification", "sendTestEmail") in [
        (service, method) for service, method, _ in backend.calls
    ]


async def test_job_output_caps_length(tmp_path: Path) -> None:
    from omv_mcp.tools.jobs_apt import job_output

    settings = Settings(
        ssh_host="127.0.0.1",
        mode=Mode.READONLY,
        response_max_bytes=5000,
        audit_path=tmp_path / "audit.jsonl",
    )
    backend = FakeBackend({("Exec", "getOutput"): {"output": "", "pos": 0, "running": True}})
    state = AppState.create(settings, backend=backend)
    ctx: Any = Ctx(state)

    await job_output(ctx, "/tmp/bgstatusabc123", pos=-1, length=10_000_000)

    params = backend.calls[-1][2]
    assert params["length"] == 5000
    assert params["pos"] == 0
    with pytest.raises(SafetyError, match="invalid job filename"):
        await job_output(ctx, "/etc/passwd")


async def test_snapraid_arrays_fetches_array_config(tmp_path: Path) -> None:
    from omv_mcp.tools.plugins.snapraid import snapraid_arrays

    settings = Settings(
        ssh_host="127.0.0.1",
        mode=Mode.READONLY,
        audit_path=tmp_path / "audit.jsonl",
    )
    backend = FakeBackend(
        {
            ("SnapRaid", "getArrayList"): {
                "total": 1,
                "data": [{"uuid": "array-1", "name": "main"}],
            },
            ("SnapRaid", "getArrayConfig"): {"config": "autosave 0\n"},
        }
    )
    state = AppState.create(settings, backend=backend)
    ctx: Any = Ctx(state)

    result = await snapraid_arrays(ctx)

    assert result["uuid"] == "array-1"
    assert result["config"] == {"config": "autosave 0\n"}
    assert backend.calls[-1][2] == {"uuid": "array-1"}


async def test_writecache_flush_passes_rotate_and_waits(tmp_path: Path) -> None:
    from omv_mcp.tools.plugins.writecache import writecache_flush

    settings = Settings(
        ssh_host="127.0.0.1",
        mode=Mode.ADMIN,
        elicit_admin=False,
        audit_path=tmp_path / "audit.jsonl",
    )
    backend = FakeBackend(
        {
            ("System", "getInformation"): {"dirtyModules": []},
            ("WriteCache", "doFlush"): "bgstatus-flush",
            ("Exec", "getOutput"): {"running": False, "output": "flushed", "pos": 7},
        }
    )
    state = AppState.create(settings, backend=backend)
    ctx: Any = Ctx(state)

    plan = await writecache_flush(ctx, rotate=True)
    assert isinstance(plan, PlanResponse)
    assert plan.rpc_calls[0]["params"] == {"rotate": True}
    result = await writecache_flush(ctx, rotate=True, confirm_token=plan.confirm_token)

    assert isinstance(result, OperationResult)
    assert result.result["output"] == "flushed"
    flush = next(
        call[2] for call in backend.calls if call[0] == "WriteCache" and call[1] == "doFlush"
    )
    assert flush == {"rotate": True}


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
