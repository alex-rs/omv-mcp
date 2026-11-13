from __future__ import annotations

from typing import Any

from fastmcp import Context

from omv_mcp.models import OperationResult, PlanResponse
from omv_mcp.rpc.redact import redact
from omv_mcp.safety.modes import Tier
from omv_mcp.tools._common import (
    ExecutionOutcome,
    PlanSpec,
    get_state,
    guarded_write,
    rpc_call_ro,
)
from omv_mcp.tools.registry import op, ro


async def writecache_settings(ctx: Context) -> Any:
    state = get_state(ctx)
    return redact(
        {
            "settings": await rpc_call_ro(state, "WriteCache", "getSettings"),
            "algorithms": await rpc_call_ro(state, "WriteCache", "getCompressionAlgorithms"),
        }
    )


async def writecache_flush(
    ctx: Context, confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[{"service": "WriteCache", "method": "doFlush", "params": {}}],
            before=None,
            after={"flushed": True},
            changes=[{"field": "writecache", "before": None, "after": "flushed"}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(result=await state.backend.call("WriteCache", "doFlush", {}))

    return await guarded_write(
        ctx=ctx,
        tool="writecache_flush",
        tier=Tier.OPERATOR,
        args={},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
    )


TOOLS = (
    ro(
        "writecache_settings",
        writecache_settings,
        "Return writecache settings.",
        "WriteCache.getSettings",
        "WriteCache.getCompressionAlgorithms",
    ),
    op("writecache_flush", writecache_flush, "Flush the writecache.", "WriteCache.doFlush"),
)
