from __future__ import annotations

from typing import Any, Literal

from fastmcp import Context

from omv_mcp.models import (
    DiskHealth,
    FsHealth,
    HealthSummary,
    OperationResult,
    Page,
    PlanResponse,
    ServiceHealth,
)
from omv_mcp.rpc.redact import redact
from omv_mcp.safety.modes import Tier
from omv_mcp.shaping import filter_sort_slice, human_bytes, project_fields, shape_page
from omv_mcp.tools._common import (
    ExecutionOutcome,
    PlanSpec,
    get_state,
    guarded_write,
    list_call,
    normalize_list,
    rpc_call_list,
    rpc_call_ro,
)
from omv_mcp.tools.registry import op, ro


async def disks_list(
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
        "DiskMgmt",
        "getList",
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        order=order,
        fields=fields,
        ctx=ctx,
    )


async def disks_rescan(
    ctx: Context, confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[{"service": "DiskMgmt", "method": "rescan", "params": {}}],
            before=None,
            after={"rescanned": True},
            changes=[{"field": "disks", "before": None, "after": "rescanned"}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        result = await state.backend.call("DiskMgmt", "rescan")
        if isinstance(result, str):
            job = await state.jobs.wait(result, state.settings.job_timeout_seconds, ctx)
            return ExecutionOutcome(result=job.model_dump(), job_id=result if job.running else None)
        return ExecutionOutcome(result=result)

    return await guarded_write(
        ctx=ctx,
        tool="disks_rescan",
        tier=Tier.OPERATOR,
        args={},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
    )


async def disks_hdparm_get(ctx: Context, uuid: str) -> Any:
    return redact(await rpc_call_ro(get_state(ctx), "DiskMgmt", "getHdParm", {"uuid": uuid}))


async def filesystems_list(
    ctx: Context,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    sort: str | None = None,
    order: Literal["asc", "desc"] = "asc",
    fields: list[str] | Literal["all"] | None = None,
) -> Page[dict[str, Any]]:
    state = get_state(ctx)
    listed = await rpc_call_list(state, "FileSystemMgmt", "getList")
    mounted = await rpc_call_ro(state, "FileSystemMgmt", "enumerateMountedFilesystems")
    _, rows = normalize_list(listed)
    _, mounts = normalize_list(mounted)
    by_device = {str(item.get("devicefile")): item for item in mounts if item.get("devicefile")}
    merged: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        mount = by_device.get(str(item.get("devicefile")), {})
        item.setdefault("mounted", bool(mount.get("mounted", item.get("mounted"))))
        for key in ("mountpoint", "used", "available", "percentage"):
            if key in mount:
                item[key] = mount[key]
        for key in ("size", "used", "available"):
            if key in item:
                item[f"{key}_h"] = human_bytes(item[key])
        merged.append(item)
    total, sliced = filter_sort_slice(
        merged,
        search=search,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )
    return shape_page(
        [project_fields(item, fields) for item in sliced],
        total=total,
        offset=offset,
        limit=limit,
        max_bytes=state.settings.response_max_bytes,
    )


async def filesystems_details(ctx: Context, devicefile: str) -> Any:
    return redact(
        await rpc_call_ro(
            get_state(ctx), "FileSystemMgmt", "getDetails", {"devicefile": devicefile}
        )
    )


async def fstab_list(
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
        "FsTab",
        "enumerateEntries",
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        order=order,
        fields=fields,
        ctx=ctx,
    )


async def smart_list(
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
        "Smart",
        "getList",
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        order=order,
        fields=fields,
        ctx=ctx,
    )


async def smart_disk(
    ctx: Context,
    devicefile: str,
    section: Literal["all", "information", "attributes", "selftest", "extended"] = "all",
) -> Any:
    state = get_state(ctx)
    result: dict[str, Any] = {}
    if section in ("all", "information"):
        result["information"] = await rpc_call_ro(
            state, "Smart", "getInformation", {"devicefile": devicefile}
        )
    if section in ("all", "attributes"):
        result["attributes"] = await rpc_call_ro(
            state, "Smart", "getAttributes", {"devicefile": devicefile}
        )
    if section in ("all", "selftest"):
        result["selftest"] = await rpc_call_ro(
            state, "Smart", "getSelfTestLogs", {"devicefile": devicefile}
        )
    if section in ("all", "extended"):
        result["extended"] = await rpc_call_ro(
            state, "Smart", "getExtendedInformation", {"devicefile": devicefile}
        )
    return redact(result)


async def smart_settings(ctx: Context) -> Any:
    state = get_state(ctx)
    return redact(
        {
            "settings": await rpc_call_ro(state, "Smart", "getSettings"),
            "devices": await rpc_call_ro(state, "Smart", "getDeviceSettings"),
            "schedule": await rpc_call_ro(state, "Smart", "getScheduleList"),
        }
    )


async def smart_run_test(
    ctx: Context, uuid: str, confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[
                {
                    "service": "Smart",
                    "method": "executeScheduledTest",
                    "params": {"uuid": uuid},
                }
            ],
            before={"uuid": uuid},
            after={"test_started": True},
            changes=[{"field": "test", "before": None, "after": "started"}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        result = await state.backend.call("Smart", "executeScheduledTest", {"uuid": uuid})
        if isinstance(result, str):
            job = await state.jobs.wait(result, state.settings.job_timeout_seconds, ctx)
            return ExecutionOutcome(result=job.model_dump(), job_id=result if job.running else None)
        return ExecutionOutcome(result=result)

    return await guarded_write(
        ctx=ctx,
        tool="smart_run_test",
        tier=Tier.OPERATOR,
        args={"uuid": uuid},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
    )


async def quota_get(
    ctx: Context, type: Literal["user", "group"] = "user", name: str | None = None
) -> Any:
    state = get_state(ctx)
    if name:
        method = "getByTypeName"
        params = {"type": type, "name": name}
    else:
        method = "get"
        params = {}
    return redact(await rpc_call_ro(state, "Quota", method, params))


async def storage_health_summary(ctx: Context) -> HealthSummary:
    state = get_state(ctx)
    info = await rpc_call_ro(state, "System", "getInformation")
    fs_result = await rpc_call_list(state, "FileSystemMgmt", "getList")
    disk_result = await rpc_call_list(state, "DiskMgmt", "getList")
    smart_result = await rpc_call_list(state, "Smart", "getList")
    services_result = await rpc_call_ro(state, "Services", "getStatus")

    _, fs_rows = normalize_list(fs_result)
    _, disk_rows = normalize_list(disk_result)
    _, smart_rows = normalize_list(smart_result)
    if isinstance(services_result, dict):
        service_rows = [
            {"name": key, **value} if isinstance(value, dict) else {"name": key, "running": value}
            for key, value in services_result.items()
        ]
    else:
        _, service_rows = normalize_list(services_result)
    smart_by_device = {
        str(item.get("devicefile")): item for item in smart_rows if item.get("devicefile")
    }

    warnings: list[str] = []
    filesystems: list[FsHealth] = []
    for row in fs_rows:
        pct = row.get("percentage")
        try:
            used = float(pct) if pct is not None else None
        except (TypeError, ValueError):
            used = None
        status = "ok"
        if used is not None and used > 95:
            status = "critical"
            warnings.append(f"{row.get('devicefile')} is {used:.0f}% full")
        elif used is not None and used > 85:
            status = "warning"
            warnings.append(f"{row.get('devicefile')} is {used:.0f}% full")
        filesystems.append(
            FsHealth(
                uuid=row.get("uuid"),
                devicefile=str(row.get("devicefile") or ""),
                label=row.get("label"),
                type=row.get("type"),
                mounted=bool(row.get("mounted")),
                used_percent=used,
                status=status,
            )
        )

    disks: list[DiskHealth] = []
    for row in disk_rows:
        devicefile = str(row.get("devicefile") or "")
        smart = smart_by_device.get(devicefile, {})
        health = str(smart.get("health") or smart.get("smart_status") or "")
        temperature = smart.get("temperature")
        try:
            temp = int(temperature) if temperature is not None else None
        except (TypeError, ValueError):
            temp = None
        power_on = smart.get("poweronhours")
        try:
            hours = int(power_on) if power_on is not None else None
        except (TypeError, ValueError):
            hours = None
        status = "ok"
        if health and health.upper() not in {"PASSED", "OK", "GOOD"}:
            status = "critical"
            warnings.append(f"{devicefile} SMART status {health}")
        if temp is not None and temp > 65:
            status = "critical"
            warnings.append(f"{devicefile} is {temp}C")
        elif temp is not None and temp > 55:
            status = "warning"
            warnings.append(f"{devicefile} is {temp}C")
        disks.append(
            DiskHealth(
                devicename=str(row.get("devicename") or ""),
                devicefile=devicefile,
                model=row.get("model"),
                size_h=human_bytes(row.get("size")) if row.get("size") else None,
                temperature=temp,
                smart_status=health or None,
                power_on_hours=hours,
                status=status,
            )
        )

    services = [
        ServiceHealth(
            name=str(row.get("name") or ""),
            title=row.get("title"),
            enabled=bool(row.get("enabled")),
            running=bool(row.get("running")),
            status="ok" if row.get("running") else "stopped",
        )
        for row in service_rows
    ]
    return HealthSummary(
        hostname=str(info.get("hostname") or ""),
        version=str(info.get("version") or ""),
        reboot_required=bool(info.get("rebootRequired")),
        dirty_modules=sorted(
            info.get("dirtyModules", {}).keys()
            if isinstance(info.get("dirtyModules"), dict)
            else info.get("dirtyModules", [])
        ),
        available_pkg_updates=int(info.get("availablePkgUpdates") or 0),
        filesystems=filesystems,
        disks=disks,
        services=services,
        warnings=warnings,
    )


TOOLS = (
    ro("disks_list", disks_list, "List physical disks.", "DiskMgmt.getList"),
    op("disks_rescan", disks_rescan, "Rescan disk devices.", "DiskMgmt.rescan"),
    ro(
        "disks_hdparm_get",
        disks_hdparm_get,
        "Return hdparm settings for a disk.",
        "DiskMgmt.getHdParm",
    ),
    ro(
        "filesystems_list",
        filesystems_list,
        "List filesystems with mount and usage data.",
        "FileSystemMgmt.getList",
        "FileSystemMgmt.enumerateMountedFilesystems",
    ),
    ro(
        "filesystems_details",
        filesystems_details,
        "Return filesystem details.",
        "FileSystemMgmt.getDetails",
    ),
    ro("fstab_list", fstab_list, "List fstab entries.", "FsTab.enumerateEntries"),
    ro("smart_list", smart_list, "List SMART-monitored devices.", "Smart.getList"),
    ro(
        "smart_disk",
        smart_disk,
        "Return SMART information for one device.",
        "Smart.getInformation",
        "Smart.getAttributes",
        "Smart.getSelfTestLogs",
        "Smart.getExtendedInformation",
    ),
    ro(
        "smart_settings",
        smart_settings,
        "Return SMART settings and schedules.",
        "Smart.getSettings",
        "Smart.getDeviceSettings",
        "Smart.getScheduleList",
    ),
    op(
        "smart_run_test",
        smart_run_test,
        "Start a scheduled SMART test and wait for it.",
        "Smart.executeScheduledTest",
    ),
    ro("quota_get", quota_get, "Return quota information.", "Quota.get", "Quota.getByTypeName"),
    ro(
        "storage_health_summary",
        storage_health_summary,
        "Summarize filesystem, disk, SMART and service health.",
        "System.getInformation",
        "FileSystemMgmt.getList",
        "DiskMgmt.getList",
        "Smart.getList",
        "Services.getStatus",
    ),
)
