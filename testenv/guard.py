from __future__ import annotations

import httpx

from omv_mcp.rpc.base import RpcBackend
from omv_mcp.settings import Backend, Settings


def assert_test_target(settings: Settings) -> None:
    if settings.backend is Backend.SSH:
        if settings.ssh_host != "127.0.0.1" or settings.ssh_port != 2222:
            raise RuntimeError("refusing: only the local OMV test VM at 127.0.0.1:2222 is allowed")
    else:
        url = httpx.URL(settings.http_url or "")
        if url.host != "127.0.0.1" or url.port not in (8080, 8081, 18080):
            raise RuntimeError(
                "refusing: only the local OMV test VM at 127.0.0.1:8080/8081/18080 is allowed"
            )


async def assert_test_vm(backend: RpcBackend) -> None:
    info = await backend.call("System", "getInformation")
    hostname = info.get("hostname") if isinstance(info, dict) else None
    if hostname != "omv-test":
        raise RuntimeError("refusing: hostname is not omv-test")
