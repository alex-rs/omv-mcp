from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from omv_mcp.settings import Backend, Mode, Settings
from omv_mcp.state import AppState
from testenv.guard import assert_test_target, assert_test_vm

STATE = Path("testenv/.state")


def ssh_settings() -> Settings:
    return Settings(
        backend=Backend.SSH,
        mode=Mode.ADMIN,
        ssh_host="127.0.0.1",
        ssh_port=2222,
        ssh_key=STATE / "id_ed25519",
        ssh_known_hosts=STATE / "known_hosts",
        elicit_admin=False,
        audit_path=STATE / "audit-integration.jsonl",
    )


@pytest.fixture(scope="session")
def settings() -> Settings:
    if os.environ.get("OMV_MCP_TEST_VM") != "1":
        pytest.skip("set OMV_MCP_TEST_VM=1 to run integration tests")
    s = ssh_settings()
    assert_test_target(s)
    if not (STATE / "id_ed25519").exists():
        pytest.skip("test VM state is missing")
    return s


class FakeCtx:
    def __init__(self, state: AppState) -> None:
        self.lifespan_context = {"state": state}
        self.progress: list[tuple[float, float | None]] = []

    async def report_progress(
        self, progress: float, total: float | None = None, message: str | None = None
    ) -> None:
        self.progress.append((progress, total))

    async def elicit(self, message: str, response_type: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(data="accept")


@pytest.fixture
async def app_state(settings: Settings) -> Any:
    state = AppState.create(settings, plugins=frozenset())
    await assert_test_vm(state.backend)
    yield state
    await state.backend.close()


@pytest.fixture
def ctx(app_state: AppState) -> FakeCtx:
    return FakeCtx(app_state)
