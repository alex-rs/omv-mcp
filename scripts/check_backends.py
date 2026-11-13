from __future__ import annotations

import asyncio
from pathlib import Path

from omv_mcp.rpc.base import RpcBackend
from omv_mcp.rpc.http import HttpBackend
from omv_mcp.rpc.ssh import SshBackend
from omv_mcp.settings import Backend, Settings
from testenv.guard import assert_test_target, assert_test_vm


async def check(settings: Settings, backend: RpcBackend) -> None:
    assert_test_target(settings)
    await assert_test_vm(backend)
    info = await backend.call("System", "getInformation")
    await backend.call("System", "noop")
    print(
        f"backend={settings.backend.value} hostname={info.get('hostname')} "
        f"version={info.get('version')} dirty={info.get('dirtyModules')}"
    )


async def main() -> None:
    ssh = Settings(
        backend=Backend.SSH,
        ssh_host="127.0.0.1",
        ssh_port=2222,
        ssh_key=Path("testenv/.state/id_ed25519"),
        ssh_known_hosts=Path("testenv/.state/known_hosts"),
    )
    http = Settings(
        backend=Backend.HTTP,
        http_url="http://127.0.0.1:18080",
        http_password=Path("testenv/.state/omv-admin.pass").read_text().strip(),
    )
    for settings in (ssh, http):
        backend: RpcBackend = (
            SshBackend(settings) if settings.backend is Backend.SSH else HttpBackend(settings)
        )
        try:
            await check(settings, backend)
        finally:
            await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
