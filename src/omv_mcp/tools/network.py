from __future__ import annotations

import json
from typing import Any

from fastmcp import Context

from omv_mcp.models import OperationResult, PlanResponse
from omv_mcp.rpc.redact import redact
from omv_mcp.safety.guard import (
    SafetyError,
    check_protected_group,
    check_protected_user,
    is_never_exposed,
    is_ro_method,
    shared_folder_refs,
)
from omv_mcp.safety.modes import Tier
from omv_mcp.schemas import read_catalog, read_schema
from omv_mcp.tools._common import (
    ExecutionOutcome,
    PlanSpec,
    get_state,
    guarded_write,
    normalize_list,
    rpc_call_list,
    rpc_call_ro,
)
from omv_mcp.tools.registry import op, ro


async def network_info(ctx: Context) -> Any:
    state = get_state(ctx)
    general = await rpc_call_ro(state, "Network", "getGeneralSettings")
    interfaces = await rpc_call_list(state, "Network", "getInterfaceList")
    _, rows = normalize_list(interfaces)
    details: list[dict[str, Any]] = []
    for row in rows:
        name = row.get("devicename") or row.get("name")
        detail: Any = None
        if name:
            try:
                detail = await rpc_call_ro(
                    state, "Network", "getInformation", {"devicename": str(name)}
                )
            except Exception as exc:
                detail = {"error": str(exc)}
        details.append({"interface": row, "information": detail})
    devices = await rpc_call_list(state, "Network", "enumerateDevicesList")
    return redact({"general": general, "interfaces": details, "devices": devices})


async def firewall_rules(ctx: Context) -> Any:
    state = get_state(ctx)
    return redact(
        {
            "ipv4": await rpc_call_ro(state, "Iptables", "getRules"),
            "ipv6": await rpc_call_ro(state, "Iptables", "getRules6"),
        }
    )


def _strip_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_keys(item)
            for key, item in value.items()
            if "private" not in str(key).lower()
        }
    if isinstance(value, list):
        return [_strip_keys(item) for item in value]
    return value


async def certificates_list(ctx: Context) -> Any:
    state = get_state(ctx)
    certs = await rpc_call_list(state, "CertificateMgmt", "getList")
    ssh = await rpc_call_list(state, "CertificateMgmt", "getSshList")
    return redact(_strip_keys({"certificates": certs, "ssh": ssh}))


async def notifications_test_email(
    ctx: Context, id: str | None = None, confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)
    service = "Notification"
    method = "sendTestEmail"
    params = {"id": id} if id else {}

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[{"service": service, "method": method, "params": params}],
            before=None,
            after={"test_email": True},
            changes=[{"field": "test_email", "before": None, "after": True}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(result=await state.backend.call(service, method, params))

    return await guarded_write(
        ctx=ctx,
        tool="notifications_test_email",
        tier=Tier.OPERATOR,
        args={"id": id},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
    )


async def rpc_describe(ctx: Context, service: str, method: str | None = None) -> Any:
    catalog = read_catalog()
    services = catalog.get("services", {})
    match = next((key for key in services if key.lower() == service.lower()), None)
    schema = read_schema(service)
    if match is None and schema is None:
        raise ValueError(f"unknown OMV service {service}")
    methods = services.get(match or service, [])
    if method:
        methods = [name for name in methods if name.lower() == method.lower()]
        if isinstance(schema, dict):
            schema = {
                key: value
                for key, value in schema.items()
                if key.rsplit(".", 1)[-1].lower() == method.lower()
            }
    return {
        "service": match or service,
        "methods": methods,
        "schema": schema,
        "source": catalog.get("source"),
        "note": None if schema else "bundled schema not captured for this service",
    }


async def rpc_call(
    ctx: Context,
    service: str,
    method: str,
    params: dict[str, Any] | None = None,
    confirm_token: str | None = None,
) -> Any:
    state = get_state(ctx)
    if is_never_exposed(service, method):
        raise SafetyError(f"RPC {service}.{method} is never exposed")
    service_key = service.casefold()
    method_key = method.casefold()
    if (
        service_key == "system"
        and method_key
        in {
            "reboot",
            "shutdown",
            "standby",
            "suspend",
            "hibernate",
        }
        and not state.settings.allow_power
    ):
        raise SafetyError("power RPCs are disabled by OMV_MCP_ALLOW_POWER")
    if service_key == "usermgmt" and method_key in {"setuser", "deleteuser"}:
        check_protected_user(str((params or {}).get("name", "")), state.settings.protected_users)
    if service_key == "usermgmt" and method_key in {"setgroup", "deletegroup"}:
        check_protected_group(str((params or {}).get("name", "")), state.settings.protected_groups)
    if service_key == "sharemgmt" and method_key == "delete":
        refs = await shared_folder_refs(state.backend, str((params or {}).get("uuid", "")))
        if refs:
            raise SafetyError("refusing: shared folder is referenced by " + ", ".join(refs))
    if is_ro_method(service, method):
        result = await state.backend.call(service, method, params or {})
        return _cap(redact(result), state.settings.response_max_bytes)

    recheck = None
    if service_key == "sharemgmt" and method_key == "delete":
        folder_uuid = str((params or {}).get("uuid", ""))

        async def recheck_folder() -> Any:
            refs = await shared_folder_refs(state.backend, folder_uuid)
            folder = await rpc_call_ro(state, "ShareMgmt", "get", {"uuid": folder_uuid})
            return {"folder": folder, "references": refs}

        recheck = recheck_folder

    async def build() -> PlanSpec:
        before = await recheck() if recheck is not None else None
        return PlanSpec(
            rpc_calls=[{"service": service, "method": method, "params": params or {}}],
            before=before,
            after=None,
            changes=[{"field": "rpc", "before": None, "after": f"{service}.{method}"}],
            recheck=recheck,
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(result=await state.backend.call(service, method, params or {}))

    if state.settings.mode is not None and state.settings.mode_tier < Tier.ADMIN:
        raise SafetyError("non-read-only rpc_call requires admin mode")
    return await guarded_write(
        ctx=ctx,
        tool="rpc_call",
        tier=Tier.ADMIN,
        args={"service": service, "method": method, "params": params or {}},
        build=build,
        execute=execute,
        confirm_token=confirm_token,
    )


def _cap(value: Any, max_bytes: int) -> Any:
    text = json.dumps(value, default=str)
    if len(text.encode()) <= max_bytes:
        return value
    return {
        "truncated": True,
        "note": "response capped; narrow the RPC params",
        "preview": text[: max_bytes // 2],
    }


TOOLS = (
    ro(
        "network_info",
        network_info,
        "Return network interfaces and configuration.",
        "Network.getGeneralSettings",
        "Network.getInterfaceList",
        "Network.getInformation",
        "Network.enumerateDevicesList",
    ),
    ro(
        "firewall_rules",
        firewall_rules,
        "Return IPv4 and IPv6 firewall rules.",
        "Iptables.getRules",
        "Iptables.getRules6",
    ),
    ro(
        "certificates_list",
        certificates_list,
        "List certificates and SSH keys without private material.",
        "CertificateMgmt.getList",
        "CertificateMgmt.getSshList",
    ),
    op(
        "notifications_test_email",
        notifications_test_email,
        "Send a test notification email.",
        "Notification.sendTestEmail",
        "EmailNotification.sendTestEmail",
    ),
    ro("rpc_describe", rpc_describe, "Describe an OMV RPC service and its bundled schema.", "none"),
    ro(
        "rpc_call",
        rpc_call,
        "Call an OMV RPC; non-read-only calls require admin mode and a confirm token.",
        "arbitrary",
    ),
)
