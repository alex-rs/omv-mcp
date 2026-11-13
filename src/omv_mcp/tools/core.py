from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastmcp import Context
from fastmcp.utilities.types import Image

from omv_mcp.models import OperationResult, Page, PlanResponse
from omv_mcp.rpc.errors import OmvRpcError
from omv_mcp.rpc.redact import redact, redact_text
from omv_mcp.safety.guard import SafetyError
from omv_mcp.safety.modes import Tier
from omv_mcp.tools._common import (
    ExecutionOutcome,
    PlanSpec,
    dirty_modules,
    get_state,
    guarded_write,
    list_call,
    rpc_call_list,
    rpc_call_ro,
)
from omv_mcp.tools.registry import admin, op, ro


async def system_info(ctx: Context, fields: list[str] | Literal["all"] | None = None) -> Any:
    state = get_state(ctx)
    result = await rpc_call_ro(state, "System", "getInformation")
    return redact(result)


async def system_top(ctx: Context, limit: int = 50) -> Any:
    state = get_state(ctx)
    try:
        result = await rpc_call_ro(state, "System", "getTopInfo", {"format": "json"})
    except OmvRpcError:
        result = await rpc_call_ro(state, "System", "getTopInfo", {"format": "text"})
        return {"format": "text", "text": redact_text(str(result))}
    if isinstance(result, dict) and isinstance(result.get("processes"), list):
        result["processes"] = result["processes"][: max(0, min(limit, 500))]
    return redact(result)


async def system_cpu(ctx: Context) -> Any:
    state = get_state(ctx)
    return redact(
        {
            "stats": await rpc_call_ro(state, "System", "getCpuStats"),
            "governors": await rpc_call_ro(state, "System", "getCpuGovernors"),
        }
    )


async def system_time(ctx: Context) -> Any:
    return redact(await rpc_call_ro(get_state(ctx), "System", "getTimeSettings"))


async def system_diagnostic_report(ctx: Context) -> dict[str, Any]:
    state = get_state(ctx)
    text = redact_text(str(await rpc_call_ro(state, "System", "getDiagnosticReport")))
    report_dir = state.settings.audit_path.parent / "reports"
    report_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = report_dir / f"diagnostic-{stamp}.txt"
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return {
        "path": str(path),
        "bytes": len(text.encode()),
        "summary": text[:4096],
    }


async def system_power(
    ctx: Context,
    action: Literal["reboot", "shutdown", "standby", "suspend", "hibernate"],
    delay: int = 0,
    confirm_token: str | None = None,
) -> PlanResponse | OperationResult:
    state = get_state(ctx)
    method = {
        "reboot": "reboot",
        "shutdown": "shutdown",
        "standby": "standby",
        "suspend": "suspend",
        "hibernate": "hibernate",
    }[action]

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[{"service": "System", "method": method, "params": {"delay": delay}}],
            before=None,
            after={"action": action, "delay": delay},
            changes=[{"field": "action", "before": None, "after": action}],
            side_effects={"network": "the NAS will lose network connectivity"},
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        await state.backend.call("System", method, {"delay": delay})
        return ExecutionOutcome(result={"action": action, "delay": delay})

    return await guarded_write(
        ctx=ctx,
        tool="system_power",
        tier=Tier.ADMIN,
        args={"action": action, "delay": delay},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
        apply=False,
    )


async def power_schedule_list(
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
        "PowerMgmt",
        "getScheduleList",
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        order=order,
        fields=fields,
        ctx=ctx,
    )


async def services_status(ctx: Context) -> Any:
    return redact(await rpc_call_ro(get_state(ctx), "Services", "getStatus"))


async def config_pending(ctx: Context) -> dict[str, Any]:
    state = get_state(ctx)
    dirty = await rpc_call_ro(state, "Config", "isDirty")
    info = await rpc_call_ro(state, "System", "getInformation")
    if not isinstance(info, dict):
        info = {}
    modules = await dirty_modules(state)
    return {
        "dirty": bool(dirty) or bool(modules),
        "modules": modules,
        "reboot_required": bool(info.get("rebootRequired")),
        "available_pkg_updates": int(info.get("availablePkgUpdates") or 0),
    }


async def logs_list(
    ctx: Context,
    id: str = "",
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    sort: str | None = None,
    order: Literal["asc", "desc"] = "asc",
    fields: list[str] | Literal["all"] | None = None,
) -> Page[dict[str, Any]]:
    return await list_call(
        get_state(ctx),
        "LogFile",
        "getList",
        params={"id": id},
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        order=order,
        fields=fields,
        ctx=ctx,
    )


async def logs_read(
    ctx: Context,
    id: str,
    tail: int = 200,
    grep: str | None = None,
) -> dict[str, Any]:
    state = get_state(ctx)
    data = await state.backend.fetch_file("LogFile", "getContent", {"id": id})
    text = redact_text(data.decode("utf-8", "replace"))
    lines = text.splitlines()
    if grep:
        lines = [line for line in lines if grep.casefold() in line.casefold()]
    lines = lines[-max(1, min(tail, 5000)) :]
    return {"id": id, "lines": len(lines), "content": "\n".join(lines)}


async def notifications_get(ctx: Context) -> Any:
    state = get_state(ctx)
    listing = await rpc_call_list(state, "Notification", "getList")
    try:
        email = await rpc_call_ro(state, "EmailNotification", "get")
    except OmvRpcError:
        email = None
    return redact({"notifications": listing, "email": email})


async def perf_graph(ctx: Context, kind: str, period: str = "day") -> Image:
    state = get_state(ctx)
    data = await state.backend.fetch_file("Rrd", "getGraph", {"kind": kind, "period": period})
    return Image(data=data, format="png")


async def config_apply(
    ctx: Context,
    modules: list[str] | None,
    force: bool = False,
    confirm_token: str | None = None,
) -> PlanResponse | OperationResult:
    state = get_state(ctx)
    args = {"modules": modules, "force": force}

    async def build() -> PlanSpec:
        current = await dirty_modules(state)
        if not modules:
            raise SafetyError(f"modules is required; current dirty modules: {current}")
        return PlanSpec(
            rpc_calls=[
                {
                    "service": "Config",
                    "method": "applyChangesBg",
                    "params": {"modules": modules, "force": force},
                }
            ],
            before={"dirty_modules": current},
            after={"modules": modules},
            changes=[{"field": "dirty_modules", "before": current, "after": []}],
            side_effects={
                "not_currently_dirty": sorted(set(modules) - set(current)),
            },
            modules_expected=set(modules),
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        assert modules is not None
        filename = await state.jobs.start(
            "Config", "applyChangesBg", {"modules": modules, "force": force}
        )
        result = await state.jobs.wait(filename, state.settings.job_timeout_seconds, ctx)
        return ExecutionOutcome(
            result=result.model_dump(),
            job_id=filename if result.running else None,
        )

    return await guarded_write(
        ctx=ctx,
        tool="config_apply",
        tier=Tier.OPERATOR,
        args=args,
        build=build,
        execute=execute,
        confirm_token=confirm_token,
        apply=False,
    )


async def config_revert(
    ctx: Context,
    confirm_token: str | None = None,
) -> PlanResponse | OperationResult:
    state = get_state(ctx)

    async def build() -> PlanSpec:
        current = await dirty_modules(state)
        return PlanSpec(
            rpc_calls=[
                {
                    "service": "Config",
                    "method": "revertChangesBg",
                    "params": {"filename": ""},
                }
            ],
            before={"dirty_modules": current},
            after={"dirty_modules": []},
            changes=[{"field": "dirty_modules", "before": current, "after": []}],
            side_effects={"reverts": "all unapplied config changes"},
            modules_expected=set(current),
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        filename = await state.jobs.start("Config", "revertChangesBg", {"filename": ""})
        result = await state.jobs.wait(filename, state.settings.job_timeout_seconds, ctx)
        return ExecutionOutcome(
            result=result.model_dump(),
            job_id=filename if result.running else None,
        )

    return await guarded_write(
        ctx=ctx,
        tool="config_revert",
        tier=Tier.OPERATOR,
        args={},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
    )


TOOLS = (
    ro(
        "system_info",
        system_info,
        "Return OMV system information and dirty modules.",
        "System.getInformation",
    ),
    ro("system_top", system_top, "Return CPU/process top information.", "System.getTopInfo"),
    ro(
        "system_cpu",
        system_cpu,
        "Return CPU statistics and available governors.",
        "System.getCpuStats",
        "System.getCpuGovernors",
    ),
    ro("system_time", system_time, "Return OMV time settings.", "System.getTimeSettings"),
    ro(
        "system_diagnostic_report",
        system_diagnostic_report,
        "Capture a redacted diagnostic report and return its local path.",
        "System.getDiagnosticReport",
    ),
    ro(
        "power_schedule_list",
        power_schedule_list,
        "List power schedules.",
        "PowerMgmt.getScheduleList",
    ),
    admin(
        "system_power",
        system_power,
        "Reboot, shut down, suspend or hibernate the NAS; only registered with OMV_MCP_ALLOW_POWER.",
        "System.reboot",
        "System.shutdown",
        "System.standby",
        "System.suspend",
        "System.hibernate",
        destructive=True,
        idempotent=False,
    ),
    ro("services_status", services_status, "List OMV service status.", "Services.getStatus"),
    ro(
        "config_pending",
        config_pending,
        "Report dirty config modules and upgrade state.",
        "Config.isDirty",
        "System.getInformation",
    ),
    op(
        "config_apply",
        config_apply,
        "Apply an explicit list of dirty OMV config modules; needs a confirm token.",
        "Config.applyChangesBg",
    ),
    op(
        "config_revert",
        config_revert,
        "Revert unapplied config changes; destructive.",
        "Config.revertChangesBg",
    ),
    ro("logs_list", logs_list, "List available log files.", "LogFile.getList"),
    ro(
        "logs_read",
        logs_read,
        "Read a log file and return the last matching lines.",
        "LogFile.getContent",
    ),
    ro(
        "notifications_get",
        notifications_get,
        "Return notification settings with secrets redacted.",
        "Notification.getList",
        "EmailNotification.get",
    ),
    ro("perf_graph", perf_graph, "Return an RRD performance graph as a PNG image.", "Rrd.getGraph"),
)
