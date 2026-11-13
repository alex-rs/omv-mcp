from __future__ import annotations

from typing import Any

from fastmcp import Context

from omv_mcp.rpc.redact import redact
from omv_mcp.tools._common import get_state, rpc_call_ro
from omv_mcp.tools.registry import ro


async def omvextras_get(ctx: Context) -> Any:
    return redact(await rpc_call_ro(get_state(ctx), "omvextras", "get"))


TOOLS = (
    ro("omvextras_get", omvextras_get, "Return omv-extras repository settings.", "omvextras.get"),
)
