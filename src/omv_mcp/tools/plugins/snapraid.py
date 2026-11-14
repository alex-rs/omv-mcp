from __future__ import annotations

from typing import Any, Literal

from fastmcp import Context

from omv_mcp.models import OperationResult, Page, PlanResponse
from omv_mcp.rpc.redact import redact
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
from omv_mcp.tools.registry import admin, op, ro


async def snapraid_arrays(ctx: Context) -> Any:
    state = get_state(ctx)
    return redact(
        {
            "arrays": await rpc_call_list(state, "SnapRaid", "getArrayList"),
            "config": await rpc_call_ro(state, "SnapRaid", "getArrayConfig"),
        }
    )


async def snapraid_drives(
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
        "SnapRaid",
        "getDriveList",
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        order=order,
        fields=fields,
        ctx=ctx,
    )


async def snapraid_rules(
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
        "SnapRaid",
        "getRuleList",
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        order=order,
        fields=fields,
        ctx=ctx,
    )


async def snapraid_config(ctx: Context) -> Any:
    state = get_state(ctx)
    return redact(
        {
            "config": await rpc_call_ro(state, "SnapRaid", "getConfig"),
            "settings": await rpc_call_ro(state, "SnapRaid", "getSettings"),
            "version": await rpc_call_ro(state, "SnapRaid", "getVersion"),
        }
    )


async def _array_uuid(state: Any, uuid: str | None) -> str:
    if uuid:
        return uuid
    result = await rpc_call_list(state, "SnapRaid", "getArrayList")
    rows = result.get("data", []) if isinstance(result, dict) else []
    if not rows:
        raise SafetyError("no SnapRAID array configured")
    return str(rows[0]["uuid"])


async def snapraid_command(
    ctx: Context,
    command: Literal["status", "diff", "smart", "scrub"],
    uuid: str | None = None,
    confirm_token: str | None = None,
) -> PlanResponse | OperationResult:
    state = get_state(ctx)
    params: dict[str, Any] = {"uuid": await _array_uuid(state, uuid), "command": command}

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[{"service": "SnapRaid", "method": "executeCommand", "params": params}],
            before=None,
            after={"command": command},
            changes=[{"field": "command", "before": None, "after": command}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        result = await state.backend.call("SnapRaid", "executeCommand", params)
        if isinstance(result, str):
            job = await state.jobs.wait(result, state.settings.job_timeout_seconds, ctx)
            return ExecutionOutcome(result=job.model_dump(), job_id=result if job.running else None)
        return ExecutionOutcome(result=result)

    return await guarded_write(
        ctx=ctx,
        tool="snapraid_command",
        tier=Tier.OPERATOR,
        args=params,
        build=build,
        execute=execute,
        confirm_token=confirm_token,
    )


async def snapraid_sync(
    ctx: Context, uuid: str | None = None, confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)
    params = {"uuid": await _array_uuid(state, uuid), "command": "sync"}

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[{"service": "SnapRaid", "method": "executeCommand", "params": params}],
            before=None,
            after={"command": "sync"},
            changes=[{"field": "command", "before": None, "after": "sync"}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        result = await state.backend.call("SnapRaid", "executeCommand", params)
        if isinstance(result, str):
            job = await state.jobs.wait(result, state.settings.job_timeout_seconds, ctx)
            return ExecutionOutcome(result=job.model_dump(), job_id=result if job.running else None)
        return ExecutionOutcome(result=result)

    return await guarded_write(
        ctx=ctx,
        tool="snapraid_sync",
        tier=Tier.ADMIN,
        args={"uuid": params["uuid"]},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
    )


TOOLS = (
    ro(
        "snapraid_arrays",
        snapraid_arrays,
        "Return snapraid arrays and configuration.",
        "SnapRaid.getArrayList",
        "SnapRaid.getArrayConfig",
    ),
    ro("snapraid_drives", snapraid_drives, "List snapraid drives.", "SnapRaid.getDriveList"),
    ro("snapraid_rules", snapraid_rules, "List snapraid rules.", "SnapRaid.getRuleList"),
    ro(
        "snapraid_config",
        snapraid_config,
        "Return snapraid config, settings and version.",
        "SnapRaid.getConfig",
        "SnapRaid.getSettings",
        "SnapRaid.getVersion",
    ),
    op(
        "snapraid_command",
        snapraid_command,
        "Run a read-only snapraid command or scrub.",
        "SnapRaid.executeCommand",
    ),
    admin(
        "snapraid_sync",
        snapraid_sync,
        "Run snapraid sync.",
        "SnapRaid.executeCommand",
        idempotent=False,
    ),
)
