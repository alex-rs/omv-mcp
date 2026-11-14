from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from omv_mcp.models import OperationResult, PlanResponse
from omv_mcp.rpc.ssh import SshBackend
from omv_mcp.settings import Backend, Mode, Settings
from omv_mcp.state import AppState
from omv_mcp.tools.core import system_power
from testenv.guard import assert_test_target, assert_test_vm

pytestmark = pytest.mark.integration
STATE = Path("testenv/.state")


class Ctx:
    def __init__(self, state: AppState) -> None:
        self.lifespan_context = {"state": state}

    async def elicit(self, message: str, response_type: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(data="accept")


def settings() -> Settings:
    return Settings(
        backend=Backend.SSH,
        mode=Mode.ADMIN,
        allow_power=True,
        elicit_admin=False,
        ssh_host="127.0.0.1",
        ssh_port=2222,
        ssh_key=STATE / "id_ed25519",
        ssh_known_hosts=STATE / "known_hosts",
        audit_path=STATE / "audit-power.jsonl",
    )


async def wait_for_reboot(settings: Settings) -> None:
    backend = SshBackend(settings)
    went_down = False
    try:
        for _ in range(80):
            try:
                await backend.call("System", "noop", timeout=5)
            except Exception:
                went_down = True
            else:
                if went_down:
                    info = await backend.call("System", "getInformation", timeout=10)
                    assert info["hostname"] == "omv-test"
                    return
            await asyncio.sleep(2)
    finally:
        await backend.close()
    raise AssertionError("test VM did not reboot")


async def test_reboot_returns_and_vm_reconnects() -> None:
    s = settings()
    assert_test_target(s)
    state = AppState.create(s)
    await assert_test_vm(state.backend)
    try:
        ctx: Any = Ctx(state)
        plan = await system_power(ctx, "reboot", delay=2)
        assert isinstance(plan, PlanResponse)
        result = await system_power(ctx, "reboot", delay=2, confirm_token=plan.confirm_token)
        assert isinstance(result, OperationResult)
    finally:
        await state.backend.close()
    await wait_for_reboot(s)
