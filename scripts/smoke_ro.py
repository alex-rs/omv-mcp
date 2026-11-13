from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from omv_mcp.server import build_server, probe_plugins
from omv_mcp.settings import Backend, Mode, Settings
from omv_mcp.state import AppState
from omv_mcp.tools.core import config_pending, system_info
from omv_mcp.tools.storage import storage_health_summary
from testenv.guard import assert_test_target, assert_test_vm


class Ctx:
    def __init__(self, state: AppState) -> None:
        self.lifespan_context = {"state": state}

    async def report_progress(self, *args: Any, **kwargs: Any) -> None:
        return None


async def main() -> None:
    settings = Settings(
        backend=Backend.SSH,
        mode=Mode.READONLY,
        ssh_host="127.0.0.1",
        ssh_port=2222,
        ssh_key=Path("testenv/.state/id_ed25519"),
        ssh_known_hosts=Path("testenv/.state/known_hosts"),
        audit_path=Path("testenv/.state/audit-smoke.jsonl"),
    )
    assert_test_target(settings)
    plugins = await probe_plugins(settings)
    server = build_server(settings, plugins=plugins)
    tools = await server.list_tools()
    mutating = [
        tool.name for tool in tools if not (tool.annotations and tool.annotations.read_only_hint)
    ]
    assert not mutating, f"readonly server exposed mutating tools: {mutating}"

    state = AppState.create(settings)
    ctx = Ctx(state)
    try:
        await assert_test_vm(state.backend)
        info = await system_info(ctx)
        pending = await config_pending(ctx)
        health = await storage_health_summary(ctx)
        print(
            f"tools={len(tools)} host={info.get('hostname')} "
            f"dirty={pending['modules']} fs={len(health.filesystems)} disks={len(health.disks)}"
        )
    finally:
        await state.backend.close()


if __name__ == "__main__":
    asyncio.run(main())
