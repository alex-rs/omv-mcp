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
    rpc_call_ro,
)
from omv_mcp.tools.registry import admin, op, ro

_LIST = dict


async def cron_list(
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
        "Cron",
        "getList",
        params={"type": ["userdefined"]},
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        order=order,
        fields=fields or ["uuid", "enable", "comment", "type", "execution", "username", "command"],
        ctx=ctx,
    )


async def cron_get(ctx: Context, uuid: str) -> Any:
    return redact(await rpc_call_ro(get_state(ctx), "Cron", "get", {"uuid": uuid}))


async def cron_run(
    ctx: Context, uuid: str, confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)

    async def build() -> PlanSpec:
        before = await rpc_call_ro(state, "Cron", "get", {"uuid": uuid})
        return PlanSpec(
            rpc_calls=[{"service": "Cron", "method": "execute", "params": {"uuid": uuid}}],
            before=before,
            after={"started": uuid},
            changes=[{"field": "job", "before": None, "after": uuid}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        result = await state.backend.call("Cron", "execute", {"uuid": uuid})
        if isinstance(result, str):
            job = await state.jobs.wait(result, state.settings.job_timeout_seconds, ctx)
            return ExecutionOutcome(result=job.model_dump(), job_id=result if job.running else None)
        return ExecutionOutcome(result=result)

    return await guarded_write(
        ctx=ctx,
        tool="cron_run",
        tier=Tier.OPERATOR,
        args={"uuid": uuid},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
    )


async def cron_set(
    ctx: Context,
    command: str,
    comment: str = "",
    uuid: str | None = None,
    enable: bool = True,
    type: str = "userdefined",
    execution: str = "daily",
    username: str = "root",
    minute: list[str] | None = None,
    hour: list[str] | None = None,
    month: list[str] | None = None,
    dayofmonth: list[str] | None = None,
    dayofweek: list[str] | None = None,
    sendemail: bool = False,
    apply: bool = False,
    confirm_token: str | None = None,
) -> PlanResponse | OperationResult:
    state = get_state(ctx)
    params = {
        "uuid": uuid or "fa4b1c66-ef79-11e5-87a0-0002b3a176b4",
        "enable": enable,
        "comment": comment,
        "type": type,
        "execution": execution,
        "sendemail": sendemail,
        "minute": minute or ["0"],
        "everynminute": False,
        "hour": hour or ["3"],
        "everynhour": False,
        "month": month or ["*"],
        "dayofmonth": dayofmonth or ["*"],
        "everyndayofmonth": False,
        "dayofweek": dayofweek or ["*"],
        "username": username,
        "command": command,
    }

    async def build() -> PlanSpec:
        before = await rpc_call_ro(state, "Cron", "get", {"uuid": params["uuid"]}) if uuid else None
        return PlanSpec(
            rpc_calls=[{"service": "Cron", "method": "set", "params": params}],
            before=before,
            after={"command": command, "username": username},
            changes=[
                {"field": "command", "before": (before or {}).get("command"), "after": command}
            ],
            modules_expected={"cron"},
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(result=await state.backend.call("Cron", "set", params))

    return await guarded_write(
        ctx=ctx,
        tool="cron_set",
        tier=Tier.ADMIN,
        args=dict(params, apply=apply),
        build=build,
        execute=execute,
        confirm_token=confirm_token,
        apply=apply,
    )


async def cron_delete(
    ctx: Context, uuid: str, apply: bool = False, confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[{"service": "Cron", "method": "delete", "params": {"uuid": uuid}}],
            before=await rpc_call_ro(state, "Cron", "get", {"uuid": uuid}),
            after=None,
            changes=[{"field": "uuid", "before": uuid, "after": None}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(result=await state.backend.call("Cron", "delete", {"uuid": uuid}))

    return await guarded_write(
        ctx=ctx,
        tool="cron_delete",
        tier=Tier.ADMIN,
        args={"uuid": uuid, "apply": apply},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
        apply=apply,
    )


async def rsync_jobs_list(
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
        "Rsync",
        "getList",
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        order=order,
        fields=fields,
        ctx=ctx,
    )


async def rsync_job_get(ctx: Context, uuid: str) -> Any:
    return redact(await rpc_call_ro(get_state(ctx), "Rsync", "get", {"uuid": uuid}))


async def rsync_run(
    ctx: Context, uuid: str, confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[{"service": "Rsync", "method": "execute", "params": {"uuid": uuid}}],
            before=await rpc_call_ro(state, "Rsync", "get", {"uuid": uuid}),
            after={"started": uuid},
            changes=[{"field": "job", "before": None, "after": uuid}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        result = await state.backend.call("Rsync", "execute", {"uuid": uuid})
        if isinstance(result, str):
            job = await state.jobs.wait(result, state.settings.job_timeout_seconds, ctx)
            return ExecutionOutcome(result=job.model_dump(), job_id=result if job.running else None)
        return ExecutionOutcome(result=result)

    return await guarded_write(
        ctx=ctx,
        tool="rsync_run",
        tier=Tier.OPERATOR,
        args={"uuid": uuid},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
    )


async def jobs_list(ctx: Context) -> Any:
    return redact(await get_state(ctx).jobs.list_jobs())


async def job_status(ctx: Context, filename: str) -> dict[str, Any]:
    state = get_state(ctx)
    return {"filename": filename, "running": await state.jobs.status(filename)}


async def job_output(ctx: Context, filename: str, pos: int = 0, length: int = 16384) -> Any:
    state = get_state(ctx)
    result = await rpc_call_ro(
        state,
        "Exec",
        "getOutput",
        {"filename": filename, "pos": pos, "length": max(1024, length)},
    )
    return redact(result)


async def job_stop(
    ctx: Context, filename: str, confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[{"service": "Exec", "method": "stop", "params": {"filename": filename}}],
            before={"filename": filename, "running": await state.jobs.status(filename)},
            after={"filename": filename, "running": False},
            changes=[{"field": "running", "before": True, "after": False}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(
            result=await state.backend.call("Exec", "stop", {"filename": filename})
        )

    return await guarded_write(
        ctx=ctx,
        tool="job_stop",
        tier=Tier.OPERATOR,
        args={"filename": filename},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
    )


async def apt_updates_list(
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
        "Apt",
        "enumerateUpgraded",
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        order=order,
        fields=fields,
        ctx=ctx,
    )


async def apt_changelog(ctx: Context, filename: str) -> Any:
    return redact(await rpc_call_ro(get_state(ctx), "Apt", "getChangeLog", {"filename": filename}))


async def apt_refresh(
    ctx: Context, confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[{"service": "Apt", "method": "update", "params": {}}],
            before=None,
            after={"updated": True},
            changes=[{"field": "apt", "before": None, "after": "refreshed"}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        result = await state.backend.call("Apt", "update")
        if isinstance(result, str):
            job = await state.jobs.wait(result, state.settings.job_timeout_seconds, ctx)
            return ExecutionOutcome(result=job.model_dump(), job_id=result if job.running else None)
        return ExecutionOutcome(result=result)

    return await guarded_write(
        ctx=ctx,
        tool="apt_refresh",
        tier=Tier.OPERATOR,
        args={},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
    )


async def apt_upgrade(
    ctx: Context, packages: list[str], confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)

    async def build() -> PlanSpec:
        if not packages:
            raise SafetyError("packages must be an explicit non-empty list")
        risky = sorted(
            set(packages)
            & {"openmediavault", "linux-image", "docker", "systemd", "openssh", "network-manager"}
        )
        return PlanSpec(
            rpc_calls=[{"service": "Apt", "method": "install", "params": {"packages": packages}}],
            before=None,
            after={"packages": packages},
            changes=[{"field": "packages", "before": None, "after": packages}],
            side_effects={"risky_packages": risky},
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        result = await state.backend.call("Apt", "install", {"packages": packages})
        if isinstance(result, str):
            job = await state.jobs.wait(result, state.settings.job_timeout_seconds, ctx)
            return ExecutionOutcome(result=job.model_dump(), job_id=result if job.running else None)
        return ExecutionOutcome(result=result)

    return await guarded_write(
        ctx=ctx,
        tool="apt_upgrade",
        tier=Tier.ADMIN,
        args={"packages": packages},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
    )


async def plugins_list(
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
        "Plugin",
        "getList",
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        order=order,
        fields=fields,
        ctx=ctx,
    )


async def plugin_install(
    ctx: Context, packages: list[str], confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[
                {"service": "Plugin", "method": "install", "params": {"packages": packages}}
            ],
            before=None,
            after={"packages": packages},
            changes=[{"field": "packages", "before": None, "after": packages}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        result = await state.backend.call("Plugin", "install", {"packages": packages})
        if isinstance(result, str):
            job = await state.jobs.wait(result, state.settings.job_timeout_seconds, ctx)
            return ExecutionOutcome(result=job.model_dump(), job_id=result if job.running else None)
        return ExecutionOutcome(result=result)

    return await guarded_write(
        ctx=ctx,
        tool="plugin_install",
        tier=Tier.ADMIN,
        args={"packages": packages},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
    )


async def plugin_remove(
    ctx: Context, packages: list[str], confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[{"service": "Plugin", "method": "remove", "params": {"packages": packages}}],
            before=None,
            after={"packages": packages},
            changes=[{"field": "packages", "before": packages, "after": None}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        result = await state.backend.call("Plugin", "remove", {"packages": packages})
        if isinstance(result, str):
            job = await state.jobs.wait(result, state.settings.job_timeout_seconds, ctx)
            return ExecutionOutcome(result=job.model_dump(), job_id=result if job.running else None)
        return ExecutionOutcome(result=result)

    return await guarded_write(
        ctx=ctx,
        tool="plugin_remove",
        tier=Tier.ADMIN,
        args={"packages": packages},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
    )


TOOLS = (
    ro("cron_list", cron_list, "List user-defined cron jobs.", "Cron.getList"),
    ro("cron_get", cron_get, "Return a cron job.", "Cron.get"),
    op("cron_run", cron_run, "Run a cron job now.", "Cron.execute"),
    admin("cron_set", cron_set, "Create or update a cron job.", "Cron.set"),
    admin("cron_delete", cron_delete, "Delete a cron job.", "Cron.delete", destructive=True),
    ro("rsync_jobs_list", rsync_jobs_list, "List rsync jobs.", "Rsync.getList"),
    ro("rsync_job_get", rsync_job_get, "Return an rsync job.", "Rsync.get"),
    op("rsync_run", rsync_run, "Run an rsync job now.", "Rsync.execute"),
    ro("jobs_list", jobs_list, "List running and finished engine jobs.", "Exec.enumerate"),
    ro("job_status", job_status, "Return whether a job is running.", "Exec.isRunning"),
    ro("job_output", job_output, "Return job output.", "Exec.getOutput"),
    op("job_stop", job_stop, "Stop a running engine job.", "Exec.stop"),
    ro(
        "apt_updates_list",
        apt_updates_list,
        "List available package upgrades.",
        "Apt.enumerateUpgraded",
    ),
    ro("apt_changelog", apt_changelog, "Return a package changelog.", "Apt.getChangeLog"),
    op("apt_refresh", apt_refresh, "Refresh apt package lists.", "Apt.update"),
    admin("apt_upgrade", apt_upgrade, "Install an explicit list of packages.", "Apt.install"),
    ro("plugins_list", plugins_list, "List plugins.", "Plugin.getList"),
    admin("plugin_install", plugin_install, "Install plugins.", "Plugin.install"),
    admin("plugin_remove", plugin_remove, "Remove plugins.", "Plugin.remove", destructive=True),
)
