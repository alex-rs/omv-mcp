from __future__ import annotations

import contextlib
import re
from typing import Any, Literal

from fastmcp import Context
from pydantic import SecretStr

from omv_mcp.models import OperationResult, Page, PlanResponse
from omv_mcp.omv import NEW_UUID
from omv_mcp.rpc.redact import redact
from omv_mcp.safety.guard import (
    SafetyError,
    check_protected_group,
    check_protected_user,
    shared_folder_refs,
)
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

_DANGEROUS_OPTIONS = re.compile(
    r"(?i)(pre[- ]?exec|post[- ]?exec|root\s+pre[- ]?exec|root\s+post[- ]?exec|"
    r"magic\s+script|no_root_squash|insecure)"
)


def _check_options(value: str | None) -> None:
    if value and _DANGEROUS_OPTIONS.search(value):
        raise SafetyError("refusing dangerous share option")


def _list_args(
    limit: int,
    offset: int,
    search: str | None,
    sort: str | None,
    order: Literal["asc", "desc"],
    fields: list[str] | Literal["all"] | None,
) -> dict[str, Any]:
    return {
        "limit": limit,
        "offset": offset,
        "search": search,
        "sort": sort,
        "order": order,
        "fields": fields,
    }


async def shared_folders_list(
    ctx: Context,
    resolve_paths: bool = False,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    sort: str | None = None,
    order: Literal["asc", "desc"] = "asc",
    fields: list[str] | Literal["all"] | None = None,
) -> Page[dict[str, Any]]:
    state = get_state(ctx)
    page = await list_call(
        state,
        "ShareMgmt",
        "getList",
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        order=order,
        fields=fields,
        ctx=ctx,
    )
    if resolve_paths:
        for item in page.items:
            uuid = item.get("uuid")
            if uuid:
                try:
                    item["absolute_path"] = await rpc_call_ro(
                        state, "ShareMgmt", "getPath", {"uuid": uuid}
                    )
                except Exception:
                    item["absolute_path"] = None
    return page


async def shared_folder_get(ctx: Context, uuid: str) -> Any:
    state = get_state(ctx)
    folder = await rpc_call_ro(state, "ShareMgmt", "get", {"uuid": uuid})
    path = None
    with contextlib.suppress(Exception):
        path = await rpc_call_ro(state, "ShareMgmt", "getPath", {"uuid": uuid})
    return redact({"folder": folder, "absolute_path": path})


async def shared_folder_candidates(ctx: Context) -> Any:
    return redact(await rpc_call_ro(get_state(ctx), "ShareMgmt", "getCandidates"))


async def shared_folder_create(
    ctx: Context,
    name: str,
    mntentref: str,
    comment: str = "",
    reldirpath: str | None = None,
    uuid: str | None = None,
    apply: bool = False,
    confirm_token: str | None = None,
) -> PlanResponse | OperationResult:
    state = get_state(ctx)
    params = {
        "uuid": uuid or NEW_UUID,
        "name": name,
        "reldirpath": reldirpath or name,
        "comment": comment,
        "mntentref": mntentref,
    }
    args = dict(params, apply=apply)

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[{"service": "ShareMgmt", "method": "set", "params": params}],
            before=None,
            after={"name": name, "mntentref": mntentref},
            changes=[{"field": "name", "before": None, "after": name}],
            modules_expected={"sharedfolders", "systemd"},
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(result=await state.backend.call("ShareMgmt", "set", params))

    return await guarded_write(
        ctx=ctx,
        tool="shared_folder_create",
        tier=Tier.OPERATOR,
        args=args,
        build=build,
        execute=execute,
        confirm_token=confirm_token,
        apply=apply,
    )


async def shared_folder_delete(
    ctx: Context,
    uuid: str,
    apply: bool = False,
    confirm_token: str | None = None,
) -> PlanResponse | OperationResult:
    state = get_state(ctx)

    async def build() -> PlanSpec:
        refs = await shared_folder_refs(state.backend, uuid)
        if refs:
            raise SafetyError("refusing: shared folder is referenced by " + ", ".join(refs))
        before = await rpc_call_ro(state, "ShareMgmt", "get", {"uuid": uuid})
        return PlanSpec(
            rpc_calls=[{"service": "ShareMgmt", "method": "delete", "params": {"uuid": uuid}}],
            before=before,
            after=None,
            changes=[{"field": "uuid", "before": uuid, "after": None}],
            side_effects={"recursive": False, "references": refs},
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(
            result=await state.backend.call(
                "ShareMgmt", "delete", {"uuid": uuid, "recursive": False}
            )
        )

    return await guarded_write(
        ctx=ctx,
        tool="shared_folder_delete",
        tier=Tier.ADMIN,
        args={"uuid": uuid, "apply": apply},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
        apply=apply,
    )


async def shared_folder_privileges_get(
    ctx: Context, uuid: str, role: str | None = None, name: str | None = None
) -> Any:
    state = get_state(ctx)
    if role and name:
        return redact(
            await rpc_call_ro(
                state,
                "ShareMgmt",
                "getPrivilegesByRole",
                {"uuid": uuid, "role": role, "name": name},
            )
        )
    return redact(await rpc_call_ro(state, "ShareMgmt", "getPrivileges", {"uuid": uuid}))


async def shared_folder_privileges_set(
    ctx: Context,
    uuid: str,
    privileges: list[dict[str, Any]],
    apply: bool = False,
    confirm_token: str | None = None,
) -> PlanResponse | OperationResult:
    state = get_state(ctx)
    params = {"uuid": uuid, "privileges": privileges}

    async def build() -> PlanSpec:
        before = await rpc_call_ro(state, "ShareMgmt", "getPrivileges", {"uuid": uuid})
        return PlanSpec(
            rpc_calls=[{"service": "ShareMgmt", "method": "setPrivileges", "params": params}],
            before=before,
            after={"privileges": privileges},
            changes=[{"field": "privileges", "before": before, "after": privileges}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(
            result=await state.backend.call("ShareMgmt", "setPrivileges", params)
        )

    return await guarded_write(
        ctx=ctx,
        tool="shared_folder_privileges_set",
        tier=Tier.OPERATOR,
        args={"uuid": uuid, "privileges": privileges, "apply": apply},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
        apply=apply,
    )


async def shared_folder_acl_get(ctx: Context, uuid: str, file: str = "") -> Any:
    return redact(
        await rpc_call_ro(get_state(ctx), "ShareMgmt", "getFileACL", {"uuid": uuid, "file": file})
    )


async def snapshots_list(
    ctx: Context,
    mntentref: str | None = None,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    sort: str | None = None,
    order: Literal["asc", "desc"] = "asc",
    fields: list[str] | Literal["all"] | None = None,
) -> Page[dict[str, Any]]:
    params = {"mntentref": mntentref} if mntentref else None
    return await list_call(
        get_state(ctx),
        "ShareMgmt",
        "enumerateAllSnapshots",
        params=params,
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        order=order,
        fields=fields,
        ctx=ctx,
    )


async def snapshot_create(
    ctx: Context,
    uuid: str,
    apply: bool = False,
    confirm_token: str | None = None,
) -> PlanResponse | OperationResult:
    state = get_state(ctx)
    params = {"uuid": uuid}

    async def build() -> PlanSpec:
        folders = await rpc_call_list(state, "ShareMgmt", "getList")
        rows = folders.get("data", []) if isinstance(folders, dict) else []
        folder = next(
            (row for row in rows if isinstance(row, dict) and row.get("uuid") == uuid),
            None,
        )
        if not folder:
            raise SafetyError(f"shared folder {uuid} not found")
        mntent = folder.get("mntent") or {}
        fsname = mntent.get("fsname")
        filesystems = await rpc_call_list(state, "FileSystemMgmt", "getList")
        fsrows = filesystems.get("data", []) if isinstance(filesystems, dict) else []
        fs = next(
            (row for row in fsrows if isinstance(row, dict) and row.get("devicefile") == fsname),
            None,
        )
        if fs is None:
            raise SafetyError("cannot resolve the shared folder filesystem")
        if fs.get("mountpoint") == "/":
            raise SafetyError("refusing to snapshot the root filesystem")
        return PlanSpec(
            rpc_calls=[{"service": "ShareMgmt", "method": "createSnapshot", "params": params}],
            before=folder,
            after={"uuid": uuid, "snapshot": "created"},
            changes=[{"field": "snapshot", "before": None, "after": "created"}],
            modules_expected=set(),
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(
            result=await state.backend.call("ShareMgmt", "createSnapshot", params)
        )

    return await guarded_write(
        ctx=ctx,
        tool="snapshot_create",
        tier=Tier.OPERATOR,
        args={"uuid": uuid, "apply": apply},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
        apply=apply,
    )


async def smb_settings(ctx: Context) -> Any:
    state = get_state(ctx)
    return redact(
        {
            "settings": await rpc_call_ro(state, "SMB", "getSettings"),
            "stats": await rpc_call_ro(state, "SMB", "getStats"),
        }
    )


async def smb_shares_list(
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
        "SMB",
        "getShareList",
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        order=order,
        fields=fields,
        ctx=ctx,
    )


async def smb_share_get(ctx: Context, uuid: str) -> Any:
    return redact(await rpc_call_ro(get_state(ctx), "SMB", "getShare", {"uuid": uuid}))


async def smb_share_set(
    ctx: Context,
    sharedfolderref: str,
    uuid: str | None = None,
    comment: str | None = None,
    guest: Literal["no", "allow", "only"] | None = None,
    readonly: bool | None = None,
    browseable: bool | None = None,
    recyclebin: bool | None = None,
    recyclemaxsize: int | None = None,
    recyclemaxage: int | None = None,
    hidedotfiles: bool | None = None,
    inheritacls: bool | None = None,
    inheritpermissions: bool | None = None,
    easupport: bool | None = None,
    storedosattributes: bool | None = None,
    hostsallow: str | None = None,
    hostsdeny: str | None = None,
    audit: bool | None = None,
    timemachine: bool | None = None,
    enable: bool | None = None,
    extraoptions: str | None = None,
    apply: bool = False,
    confirm_token: str | None = None,
) -> PlanResponse | OperationResult:
    state = get_state(ctx)
    if extraoptions is not None:
        _check_options(extraoptions)
    params: dict[str, Any] = {
        "uuid": uuid or NEW_UUID,
        "sharedfolderref": sharedfolderref,
    }
    for key, value in (
        ("comment", comment),
        ("guest", guest),
        ("readonly", readonly),
        ("browseable", browseable),
        ("recyclebin", recyclebin),
        ("recyclemaxsize", recyclemaxsize),
        ("recyclemaxage", recyclemaxage),
        ("hidedotfiles", hidedotfiles),
        ("inheritacls", inheritacls),
        ("inheritpermissions", inheritpermissions),
        ("easupport", easupport),
        ("storedosattributes", storedosattributes),
        ("hostsallow", hostsallow),
        ("hostsdeny", hostsdeny),
        ("audit", audit),
        ("timemachine", timemachine),
        ("enable", enable),
        ("extraoptions", extraoptions),
    ):
        if value is not None:
            params[key] = value
    defaults: dict[str, Any] = {
        "comment": "",
        "guest": "no",
        "readonly": False,
        "browseable": True,
        "recyclebin": False,
        "recyclemaxsize": 0,
        "recyclemaxage": 0,
        "hidedotfiles": False,
        "inheritacls": False,
        "inheritpermissions": False,
        "easupport": False,
        "storedosattributes": False,
        "hostsallow": "",
        "hostsdeny": "",
        "audit": False,
        "timemachine": False,
        "enable": True,
        "extraoptions": "",
    }

    async def build() -> PlanSpec:
        before = None
        if uuid:
            before = await rpc_call_ro(state, "SMB", "getShare", {"uuid": uuid})
            if isinstance(before, dict):
                for key, value in before.items():
                    if key not in {"name", "uuid"} and key not in params:
                        params[key] = value
        for key, value in defaults.items():
            params.setdefault(key, value)
        return PlanSpec(
            rpc_calls=[{"service": "SMB", "method": "setShare", "params": params}],
            before=before,
            after={"sharedfolderref": sharedfolderref},
            changes=[
                {
                    "field": "sharedfolderref",
                    "before": (before or {}).get("sharedfolderref"),
                    "after": sharedfolderref,
                }
            ],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(result=await state.backend.call("SMB", "setShare", params))

    return await guarded_write(
        ctx=ctx,
        tool="smb_share_set",
        tier=Tier.OPERATOR,
        args=dict(params, apply=apply),
        build=build,
        execute=execute,
        confirm_token=confirm_token,
        apply=apply,
    )


async def smb_share_delete(
    ctx: Context, uuid: str, apply: bool = False, confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[{"service": "SMB", "method": "deleteShare", "params": {"uuid": uuid}}],
            before=await rpc_call_ro(state, "SMB", "getShare", {"uuid": uuid}),
            after=None,
            changes=[{"field": "uuid", "before": uuid, "after": None}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(
            result=await state.backend.call("SMB", "deleteShare", {"uuid": uuid})
        )

    return await guarded_write(
        ctx=ctx,
        tool="smb_share_delete",
        tier=Tier.OPERATOR,
        args={"uuid": uuid, "apply": apply},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
        apply=apply,
    )


async def nfs_settings(ctx: Context) -> Any:
    state = get_state(ctx)
    return redact(
        {
            "settings": await rpc_call_ro(state, "NFS", "getSettings"),
            "stats": await rpc_call_ro(state, "NFS", "getStats"),
        }
    )


async def nfs_shares_list(
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
        "NFS",
        "getShareList",
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        order=order,
        fields=fields,
        ctx=ctx,
    )


async def nfs_share_get(ctx: Context, uuid: str) -> Any:
    return redact(await rpc_call_ro(get_state(ctx), "NFS", "getShare", {"uuid": uuid}))


async def nfs_share_set(
    ctx: Context,
    sharedfolderref: str,
    mntentref: str,
    client: str | None = None,
    options: str | None = None,
    uuid: str | None = None,
    comment: str | None = None,
    extraoptions: str | None = None,
    apply: bool = False,
    confirm_token: str | None = None,
) -> PlanResponse | OperationResult:
    state = get_state(ctx)
    if options is not None:
        _check_options(options)
    if extraoptions is not None:
        _check_options(extraoptions)
    params: dict[str, Any] = {
        "uuid": uuid or NEW_UUID,
        "sharedfolderref": sharedfolderref,
        "mntentref": mntentref,
    }
    for key, value in (
        ("client", client),
        ("options", options),
        ("comment", comment),
        ("extraoptions", extraoptions),
    ):
        if value is not None:
            params[key] = value
    defaults = {
        "client": "*",
        "options": "rw",
        "comment": "",
        "extraoptions": "sec=sys",
    }

    async def build() -> PlanSpec:
        before = (
            await rpc_call_ro(state, "NFS", "getShare", {"uuid": params["uuid"]}) if uuid else None
        )
        if isinstance(before, dict):
            for key, value in before.items():
                if key not in {"uuid"} and key not in params:
                    params[key] = value
        for key, value in defaults.items():
            params.setdefault(key, value)
        return PlanSpec(
            rpc_calls=[{"service": "NFS", "method": "setShare", "params": params}],
            before=before,
            after={"sharedfolderref": sharedfolderref, "client": params["client"]},
            changes=[
                {
                    "field": key,
                    "before": (before or {}).get(key),
                    "after": params.get(key),
                }
                for key in ("sharedfolderref", "client", "options", "comment", "extraoptions")
            ],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(result=await state.backend.call("NFS", "setShare", params))

    return await guarded_write(
        ctx=ctx,
        tool="nfs_share_set",
        tier=Tier.OPERATOR,
        args=dict(params, apply=apply),
        build=build,
        execute=execute,
        confirm_token=confirm_token,
        apply=apply,
    )


async def nfs_share_delete(
    ctx: Context, uuid: str, apply: bool = False, confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[{"service": "NFS", "method": "deleteShare", "params": {"uuid": uuid}}],
            before=await rpc_call_ro(state, "NFS", "getShare", {"uuid": uuid}),
            after=None,
            changes=[{"field": "uuid", "before": uuid, "after": None}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(
            result=await state.backend.call("NFS", "deleteShare", {"uuid": uuid})
        )

    return await guarded_write(
        ctx=ctx,
        tool="nfs_share_delete",
        tier=Tier.OPERATOR,
        args={"uuid": uuid, "apply": apply},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
        apply=apply,
    )


async def rsyncd_settings(ctx: Context) -> Any:
    return redact(await rpc_call_ro(get_state(ctx), "Rsyncd", "getSettings"))


async def rsyncd_modules_list(
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
        "Rsyncd",
        "getModuleList",
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        order=order,
        fields=fields,
        ctx=ctx,
    )


async def rsyncd_module_get(ctx: Context, uuid: str) -> Any:
    return redact(await rpc_call_ro(get_state(ctx), "Rsyncd", "getModule", {"uuid": uuid}))


async def rsyncd_module_set(
    ctx: Context,
    name: str,
    sharedfolderref: str,
    uuid: str | None = None,
    comment: str | None = None,
    uid: str | None = None,
    gid: str | None = None,
    readonly: bool | None = None,
    writeonly: bool | None = None,
    maxconnections: int | None = None,
    list: bool | None = None,
    hostsallow: str | None = None,
    hostsdeny: str | None = None,
    authusers: bool | None = None,
    usechroot: bool | None = None,
    users: list[dict[str, str]] | None = None,
    extraoptions: str | None = None,
    enable: bool | None = None,
    apply: bool = False,
    confirm_token: str | None = None,
) -> PlanResponse | OperationResult:
    state = get_state(ctx)
    if extraoptions is not None:
        _check_options(extraoptions)
    params: dict[str, Any] = {
        "uuid": uuid or NEW_UUID,
        "sharedfolderref": sharedfolderref,
        "name": name,
    }
    for key, value in (
        ("comment", comment),
        ("uid", uid),
        ("gid", gid),
        ("readonly", readonly),
        ("writeonly", writeonly),
        ("maxconnections", maxconnections),
        ("list", list),
        ("hostsallow", hostsallow),
        ("hostsdeny", hostsdeny),
        ("authusers", authusers),
        ("usechroot", usechroot),
        ("users", users),
        ("extraoptions", extraoptions),
        ("enable", enable),
    ):
        if value is not None:
            params[key] = value
    defaults: dict[str, Any] = {
        "comment": "",
        "uid": "nobody",
        "gid": "nogroup",
        "readonly": True,
        "writeonly": False,
        "maxconnections": 0,
        "list": True,
        "hostsallow": "",
        "hostsdeny": "",
        "authusers": False,
        "usechroot": True,
        "users": [],
        "extraoptions": "",
        "enable": True,
    }

    async def build() -> PlanSpec:
        before = (
            await rpc_call_ro(state, "Rsyncd", "getModule", {"uuid": params["uuid"]})
            if uuid
            else None
        )
        if isinstance(before, dict):
            for key, value in before.items():
                if key not in {"uuid"} and key not in params:
                    params[key] = value
        for key, value in defaults.items():
            params.setdefault(key, value)
        return PlanSpec(
            rpc_calls=[{"service": "Rsyncd", "method": "setModule", "params": params}],
            before=before,
            after={"name": name, "sharedfolderref": sharedfolderref},
            changes=[
                {
                    "field": key,
                    "before": (before or {}).get(key),
                    "after": params.get(key),
                }
                for key in ("name", "sharedfolderref", "comment", "readonly", "enable")
            ],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(result=await state.backend.call("Rsyncd", "setModule", params))

    return await guarded_write(
        ctx=ctx,
        tool="rsyncd_module_set",
        tier=Tier.OPERATOR,
        args=dict(params, apply=apply),
        build=build,
        execute=execute,
        confirm_token=confirm_token,
        apply=apply,
    )


async def rsyncd_module_delete(
    ctx: Context, uuid: str, apply: bool = False, confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[{"service": "Rsyncd", "method": "deleteModule", "params": {"uuid": uuid}}],
            before=await rpc_call_ro(state, "Rsyncd", "getModule", {"uuid": uuid}),
            after=None,
            changes=[{"field": "uuid", "before": uuid, "after": None}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(
            result=await state.backend.call("Rsyncd", "deleteModule", {"uuid": uuid})
        )

    return await guarded_write(
        ctx=ctx,
        tool="rsyncd_module_delete",
        tier=Tier.OPERATOR,
        args={"uuid": uuid, "apply": apply},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
        apply=apply,
    )


async def ssh_settings(ctx: Context) -> Any:
    state = get_state(ctx)
    settings = await rpc_call_ro(state, "SSH", "get")
    stats: Any = None
    with contextlib.suppress(Exception):
        stats = await rpc_call_ro(state, "SSH", "getStats")
    return redact({"settings": settings, "stats": stats})


async def users_list(
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
        "UserMgmt",
        "getUserList",
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        order=order,
        fields=fields or ["name", "comment", "uid", "gid", "groups", "email", "disabled"],
        ctx=ctx,
    )


async def user_get(ctx: Context, name: str) -> Any:
    return redact(await rpc_call_ro(get_state(ctx), "UserMgmt", "getUser", {"name": name}))


async def groups_list(
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
        "UserMgmt",
        "getGroupList",
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        order=order,
        fields=fields or ["name", "comment", "gid", "members"],
        ctx=ctx,
    )


async def group_get(ctx: Context, name: str) -> Any:
    return redact(await rpc_call_ro(get_state(ctx), "UserMgmt", "getGroup", {"name": name}))


async def user_set(
    ctx: Context,
    name: str,
    comment: str | None = None,
    email: str | None = None,
    groups: list[str] | None = None,
    shell: str | None = None,
    uid: int | None = None,
    password: SecretStr | None = None,
    disallowusermod: bool | None = None,
    sshpubkeys: list[str] | None = None,
    apply: bool = False,
    confirm_token: str | None = None,
) -> PlanResponse | OperationResult:
    state = get_state(ctx)
    check_protected_user(name, state.settings.protected_users)
    if uid is not None and uid < 1000:
        raise SafetyError("refusing to assign a system uid")
    for group in groups or []:
        if group in {"root", "admin", "sudo"}:
            raise SafetyError(f"refusing to add user to privileged group {group}")
    base_args: dict[str, Any] = {"name": name, "apply": apply}
    for key, value in (
        ("comment", comment),
        ("email", email),
        ("groups", groups),
        ("shell", shell),
        ("uid", uid),
        ("disallowusermod", disallowusermod),
        ("sshpubkeys", sshpubkeys),
        ("password", password),
    ):
        if value is not None:
            base_args[key] = value
    params: dict[str, Any] = {"name": name}
    for key, value in (
        ("comment", comment),
        ("email", email),
        ("groups", groups),
        ("shell", shell),
        ("uid", uid),
        ("disallowusermod", disallowusermod),
        ("sshpubkeys", sshpubkeys),
    ):
        if value is not None:
            params[key] = value
    if password is not None:
        params["password"] = password.get_secret_value()

    async def build() -> PlanSpec:
        before: dict[str, Any] | None = None
        with contextlib.suppress(Exception):
            loaded = await rpc_call_ro(state, "UserMgmt", "getUser", {"name": name})
            before = loaded if isinstance(loaded, dict) else None
        defaults: dict[str, Any] = {
            "groups": [],
            "password": "",
            "email": "",
            "disallowusermod": False,
            "sshpubkeys": [],
        }
        if before:
            for key, value in before.items():
                if key == "password":
                    continue
                params.setdefault(key, value)
        for key, value in defaults.items():
            params.setdefault(key, value)
        return PlanSpec(
            rpc_calls=[{"service": "UserMgmt", "method": "setUser", "params": params}],
            before=before,
            after={k: v for k, v in params.items() if k != "password"},
            changes=[
                {"field": k, "before": (before or {}).get(k), "after": v}
                for k, v in params.items()
                if k != "password"
            ],
            modules_expected={"postfix", "user"},
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(
            result=await state.backend.call("UserMgmt", "setUser", plan.rpc_calls[0]["params"])
        )

    return await guarded_write(
        ctx=ctx,
        tool="user_set",
        tier=Tier.OPERATOR,
        args=base_args,
        build=build,
        execute=execute,
        confirm_token=confirm_token,
        apply=apply,
    )


async def group_set(
    ctx: Context,
    name: str,
    comment: str | None = None,
    members: list[str] | None = None,
    apply: bool = False,
    confirm_token: str | None = None,
) -> PlanResponse | OperationResult:
    state = get_state(ctx)
    check_protected_group(name, state.settings.protected_groups)
    base_args: dict[str, Any] = {"name": name, "apply": apply}
    if comment is not None:
        base_args["comment"] = comment
    if members is not None:
        base_args["members"] = members
    params: dict[str, Any] = {"name": name}
    if comment is not None:
        params["comment"] = comment
    if members is not None:
        params["members"] = members

    async def build() -> PlanSpec:
        before: dict[str, Any] | None = None
        with contextlib.suppress(Exception):
            loaded = await rpc_call_ro(state, "UserMgmt", "getGroup", {"name": name})
            before = loaded if isinstance(loaded, dict) else None
        if before:
            params.setdefault("comment", before.get("comment", ""))
            params.setdefault("members", before.get("members", []))
        else:
            params.setdefault("comment", "")
            params.setdefault("members", [])
        return PlanSpec(
            rpc_calls=[{"service": "UserMgmt", "method": "setGroup", "params": params}],
            before=before,
            after={
                "name": name,
                "comment": params.get("comment"),
                "members": params.get("members"),
            },
            changes=[
                {"field": k, "before": (before or {}).get(k), "after": v} for k, v in params.items()
            ],
            modules_expected={"postfix", "user"},
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(
            result=await state.backend.call("UserMgmt", "setGroup", plan.rpc_calls[0]["params"])
        )

    return await guarded_write(
        ctx=ctx,
        tool="group_set",
        tier=Tier.OPERATOR,
        args=base_args,
        build=build,
        execute=execute,
        confirm_token=confirm_token,
        apply=apply,
    )


async def user_delete(
    ctx: Context, name: str, confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)

    async def build() -> PlanSpec:
        check_protected_user(name, state.settings.protected_users)
        return PlanSpec(
            rpc_calls=[{"service": "UserMgmt", "method": "deleteUser", "params": {"name": name}}],
            before=await rpc_call_ro(state, "UserMgmt", "getUser", {"name": name}),
            after=None,
            changes=[{"field": "name", "before": name, "after": None}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(
            result=await state.backend.call("UserMgmt", "deleteUser", {"name": name})
        )

    return await guarded_write(
        ctx=ctx,
        tool="user_delete",
        tier=Tier.ADMIN,
        args={"name": name},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
    )


async def group_delete(
    ctx: Context, name: str, confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)

    async def build() -> PlanSpec:
        check_protected_group(name, state.settings.protected_groups)
        return PlanSpec(
            rpc_calls=[{"service": "UserMgmt", "method": "deleteGroup", "params": {"name": name}}],
            before=await rpc_call_ro(state, "UserMgmt", "getGroup", {"name": name}),
            after=None,
            changes=[{"field": "name", "before": name, "after": None}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(
            result=await state.backend.call("UserMgmt", "deleteGroup", {"name": name})
        )

    return await guarded_write(
        ctx=ctx,
        tool="group_delete",
        tier=Tier.ADMIN,
        args={"name": name},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
    )


TOOLS = (
    ro("shared_folders_list", shared_folders_list, "List shared folders.", "ShareMgmt.getList"),
    ro(
        "shared_folder_get",
        shared_folder_get,
        "Return a shared folder and its path.",
        "ShareMgmt.get",
        "ShareMgmt.getPath",
    ),
    ro(
        "shared_folder_candidates",
        shared_folder_candidates,
        "List filesystems that can host shared folders.",
        "ShareMgmt.getCandidates",
    ),
    op("shared_folder_create", shared_folder_create, "Create a shared folder.", "ShareMgmt.set"),
    admin(
        "shared_folder_delete",
        shared_folder_delete,
        "Delete a shared folder if unreferenced.",
        "ShareMgmt.delete",
        destructive=True,
    ),
    ro(
        "shared_folder_privileges_get",
        shared_folder_privileges_get,
        "Return shared-folder privileges.",
        "ShareMgmt.getPrivileges",
        "ShareMgmt.getPrivilegesByRole",
    ),
    op(
        "shared_folder_privileges_set",
        shared_folder_privileges_set,
        "Set shared-folder privileges.",
        "ShareMgmt.setPrivileges",
    ),
    ro("shared_folder_acl_get", shared_folder_acl_get, "Return file ACLs.", "ShareMgmt.getFileACL"),
    ro("snapshots_list", snapshots_list, "List snapshots.", "ShareMgmt.enumerateAllSnapshots"),
    op("snapshot_create", snapshot_create, "Create a btrfs snapshot.", "ShareMgmt.createSnapshot"),
    ro("smb_settings", smb_settings, "Return SMB settings.", "SMB.getSettings", "SMB.getStats"),
    ro("smb_shares_list", smb_shares_list, "List SMB shares.", "SMB.getShareList"),
    ro("smb_share_get", smb_share_get, "Return an SMB share.", "SMB.getShare"),
    op("smb_share_set", smb_share_set, "Create or update an SMB share.", "SMB.setShare"),
    op(
        "smb_share_delete",
        smb_share_delete,
        "Delete an SMB share.",
        "SMB.deleteShare",
        destructive=True,
    ),
    ro("nfs_settings", nfs_settings, "Return NFS settings.", "NFS.getSettings", "NFS.getStats"),
    ro("nfs_shares_list", nfs_shares_list, "List NFS shares.", "NFS.getShareList"),
    ro("nfs_share_get", nfs_share_get, "Return an NFS share.", "NFS.getShare"),
    op("nfs_share_set", nfs_share_set, "Create or update an NFS share.", "NFS.setShare"),
    op(
        "nfs_share_delete",
        nfs_share_delete,
        "Delete an NFS share.",
        "NFS.deleteShare",
        destructive=True,
    ),
    ro("rsyncd_settings", rsyncd_settings, "Return rsyncd settings.", "Rsyncd.getSettings"),
    ro("rsyncd_modules_list", rsyncd_modules_list, "List rsyncd modules.", "Rsyncd.getModuleList"),
    ro("rsyncd_module_get", rsyncd_module_get, "Return an rsyncd module.", "Rsyncd.getModule"),
    op(
        "rsyncd_module_set",
        rsyncd_module_set,
        "Create or update an rsyncd module.",
        "Rsyncd.setModule",
    ),
    op(
        "rsyncd_module_delete",
        rsyncd_module_delete,
        "Delete an rsyncd module.",
        "Rsyncd.deleteModule",
    ),
    ro(
        "ssh_settings",
        ssh_settings,
        "Return SSH settings, public keys only.",
        "SSH.get",
        "SSH.getStats",
    ),
    ro("users_list", users_list, "List users.", "UserMgmt.getUserList"),
    ro("user_get", user_get, "Return a user.", "UserMgmt.getUser"),
    ro("groups_list", groups_list, "List groups.", "UserMgmt.getGroupList"),
    ro("group_get", group_get, "Return a group.", "UserMgmt.getGroup"),
    op("user_set", user_set, "Create or update a user.", "UserMgmt.setUser"),
    op("group_set", group_set, "Create or update a group.", "UserMgmt.setGroup"),
    admin("user_delete", user_delete, "Delete a user.", "UserMgmt.deleteUser", destructive=True),
    admin(
        "group_delete", group_delete, "Delete a group.", "UserMgmt.deleteGroup", destructive=True
    ),
)
