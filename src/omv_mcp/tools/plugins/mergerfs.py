from __future__ import annotations

from typing import Any, Literal

from fastmcp import Context

from omv_mcp.models import OperationResult, Page, PlanResponse
from omv_mcp.safety.guard import SafetyError
from omv_mcp.safety.modes import Tier
from omv_mcp.tools._common import (
    ExecutionOutcome,
    PlanSpec,
    get_state,
    guarded_write,
    list_call,
    rpc_call_list,
    rpc_call_ro,
)
from omv_mcp.tools.registry import admin, ro


async def mergerfs_pools(
    ctx: Context,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    sort: str | None = None,
    order: Literal["asc", "desc"] = "asc",
    fields: list[str] | Literal["all"] | None = None,
) -> Page[dict[str, Any]]:
    return await list_call(
        get_state(ctx),
        "Mergerfs",
        "getList",
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        order=order,
        fields=fields,
        ctx=ctx,
    )


async def mergerfs_restart_pool(
    ctx: Context, name: str, confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)

    async def build() -> PlanSpec:
        pools = await rpc_call_list(state, "Mergerfs", "getList")
        rows = pools.get("data", []) if isinstance(pools, dict) else []
        pool = next(
            (row for row in rows if isinstance(row, dict) and row.get("name") == name),
            None,
        )
        if not pool:
            raise SafetyError(f"mergerfs pool {name} not found")
        uuid = str(pool["uuid"])
        return PlanSpec(
            rpc_calls=[{"service": "Mergerfs", "method": "restartPool", "params": {"uuid": uuid}}],
            before=await rpc_call_ro(state, "Mergerfs", "get", {"uuid": uuid}),
            after={"name": name, "restarted": True},
            changes=[{"field": "pool", "before": name, "after": "restarted"}],
            side_effects={"mount": "pool is briefly unavailable"},
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        uuid = str(plan.rpc_calls[0]["params"]["uuid"])
        return ExecutionOutcome(
            result=await state.backend.call("Mergerfs", "restartPool", {"uuid": uuid})
        )

    return await guarded_write(
        ctx=ctx,
        tool="mergerfs_restart_pool",
        tier=Tier.ADMIN,
        args={"name": name},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
    )


TOOLS = (
    ro("mergerfs_pools", mergerfs_pools, "List mergerfs pools.", "Mergerfs.getList"),
    admin(
        "mergerfs_restart_pool",
        mergerfs_restart_pool,
        "Restart a mergerfs pool.",
        "Mergerfs.restartPool",
    ),
)
