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
    rpc_call_ro,
)
from omv_mcp.tools.registry import admin, op, ro


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


ALLOWED_TOOLS = frozenset({"df", "du", "info", "mount", "paths", "stats", "xattr"})


async def mergerfs_tools(
    ctx: Context,
    name: str,
    command: str,
    args: list[str] | None = None,
    confirm_token: str | None = None,
) -> PlanResponse | OperationResult:
    state = get_state(ctx)
    if command not in ALLOWED_TOOLS:
        raise SafetyError(f"mergerfs command {command} is not read-only and is not exposed")
    params = {"name": name, "command": command, "args": args or []}

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[{"service": "Mergerfs", "method": "toolsCommand", "params": params}],
            before={"pool": name},
            after={"command": command, "args": args or []},
            changes=[{"field": "command", "before": None, "after": command}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(result=await state.backend.call("Mergerfs", "toolsCommand", params))

    return await guarded_write(
        ctx=ctx,
        tool="mergerfs_tools",
        tier=Tier.OPERATOR,
        args=params,
        build=build,
        execute=execute,
        confirm_token=confirm_token,
    )


async def mergerfs_restart_pool(
    ctx: Context, name: str, confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[{"service": "Mergerfs", "method": "restartPool", "params": {"name": name}}],
            before=await rpc_call_ro(state, "Mergerfs", "get", {"name": name}),
            after={"name": name, "restarted": True},
            changes=[{"field": "pool", "before": name, "after": "restarted"}],
            side_effects={"mount": "pool is briefly unavailable"},
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(
            result=await state.backend.call("Mergerfs", "restartPool", {"name": name})
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
    op("mergerfs_tools", mergerfs_tools, "Run a read-only mergerfs tool.", "Mergerfs.toolsCommand"),
    admin(
        "mergerfs_restart_pool",
        mergerfs_restart_pool,
        "Restart a mergerfs pool.",
        "Mergerfs.restartPool",
    ),
)
