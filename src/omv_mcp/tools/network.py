from __future__ import annotations

import json
from typing import Any

from fastmcp import Context

from omv_mcp.models import OperationResult, PlanResponse
from omv_mcp.rpc.redact import redact
from omv_mcp.safety.guard import SafetyError, is_never_exposed, is_ro_method
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
    service = "Notification" if id else "EmailNotification"
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
    if is_ro_method(service, method):
        result = await state.backend.call(service, method, params or {})
        return _cap(redact(result), state.settings.response_max_bytes)

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[{"service": service, "method": method, "params": params or {}}],
            before=None,
            after=None,
            changes=[{"field": "rpc", "before": None, "after": f"{service}.{method}"}],
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
