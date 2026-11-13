from __future__ import annotations

from typing import Any

from fastmcp import Context

from omv_mcp.rpc.redact import redact
from omv_mcp.tools._common import get_state, rpc_call_ro
from omv_mcp.tools.registry import ro

_SECRET_KEYS = ("privatekey", "presharedkey", "private_key", "preshared_key")


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip(item)
            for key, item in value.items()
            if not any(secret in str(key).lower() for secret in _SECRET_KEYS)
        }
    if isinstance(value, list):
        return [_strip(item) for item in value]
    return value


async def wireguard_tunnels(ctx: Context) -> Any:
    state = get_state(ctx)
    return redact(_strip(await rpc_call_ro(state, "Wireguard", "getTunnelList")))


async def wireguard_clients(ctx: Context) -> Any:
    state = get_state(ctx)
    return redact(_strip(await rpc_call_ro(state, "Wireguard", "getClientList")))


TOOLS = (
    ro(
        "wireguard_tunnels",
        wireguard_tunnels,
        "List WireGuard tunnels without private keys.",
        "Wireguard.getTunnelList",
    ),
    ro(
        "wireguard_clients",
        wireguard_clients,
        "List WireGuard clients without private keys.",
        "Wireguard.getClientList",
    ),
)
