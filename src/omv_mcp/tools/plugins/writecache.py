from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastmcp import Context

from omv_mcp.models import OperationResult, PlanResponse
from omv_mcp.rpc.redact import redact
from omv_mcp.safety.modes import Tier
from omv_mcp.tools._common import (
    ExecutionOutcome,
    PlanSpec,
    get_object,
    get_state,
    guarded_write,
    rpc_call_ro,
)
from omv_mcp.tools.registry import op, ro

_SETTINGS_KEYS = (
    "enable",
    "use_tmpfs",
    "sharedfolderref",
    "tmpfs_size",
    "ram_backing",
    "zram_size",
    "zram_algo",
    "journald_storage",
    "flush_on_boot",
    "flush_on_shutdown",
    "rotate_on_shutdown",
    "flush_hourly",
    "flush_daily",
    "hour",
    "minute",
    "rotate_on_daily_flush",
    "paths",
    "services",
)
_ENUMS: dict[str, frozenset[str]] = {
    "ram_backing": frozenset({"tmpfs", "zram"}),
    "journald_storage": frozenset({"auto", "volatile", "persistent"}),
}


def _normalize_entries(value: str) -> str:
    # WriteCache.setSettings accepts commas or newlines, trims and deduplicates.
    seen: list[str] = []
    for item in value.replace(",", "\n").splitlines():
        item = item.strip()
        if item and item not in seen:
            seen.append(item)
    return "\n".join(seen)


def _check_overrides(overrides: Mapping[str, Any]) -> None:
    for key, allowed in _ENUMS.items():
        value = overrides.get(key)
        if value is not None and value not in allowed:
            raise ValueError(f"{key} must be one of {sorted(allowed)}")
    for key, upper in (("hour", 23), ("minute", 59)):
        value = overrides.get(key)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= upper
        ):
            raise ValueError(f"{key} must be an integer between 0 and {upper}")
    for key in ("tmpfs_size", "zram_size", "zram_algo"):
        value = overrides.get(key)
        if value is not None and not value.strip():
            raise ValueError(f"{key} must not be empty")


async def writecache_settings(ctx: Context) -> Any:
    state = get_state(ctx)
    return redact(
        {
            "settings": await rpc_call_ro(state, "WriteCache", "getSettings"),
            "algorithms": await rpc_call_ro(state, "WriteCache", "getCompressionAlgorithms"),
        }
    )


async def writecache_set(
    ctx: Context,
    enable: bool | None = None,
    use_tmpfs: bool | None = None,
    sharedfolderref: str | None = None,
    tmpfs_size: str | None = None,
    ram_backing: str | None = None,
    zram_size: str | None = None,
    zram_algo: str | None = None,
    journald_storage: str | None = None,
    flush_on_boot: bool | None = None,
    flush_on_shutdown: bool | None = None,
    rotate_on_shutdown: bool | None = None,
    flush_hourly: bool | None = None,
    flush_daily: bool | None = None,
    hour: int | None = None,
    minute: int | None = None,
    rotate_on_daily_flush: bool | None = None,
    paths: str | None = None,
    services: str | None = None,
    apply: bool = False,
    confirm_token: str | None = None,
) -> PlanResponse | OperationResult:
    state = get_state(ctx)
    overrides = {
        key: value
        for key, value in (
            ("enable", enable),
            ("use_tmpfs", use_tmpfs),
            ("sharedfolderref", sharedfolderref),
            ("tmpfs_size", tmpfs_size),
            ("ram_backing", ram_backing),
            ("zram_size", zram_size),
            ("zram_algo", zram_algo),
            ("journald_storage", journald_storage),
            ("flush_on_boot", flush_on_boot),
            ("flush_on_shutdown", flush_on_shutdown),
            ("rotate_on_shutdown", rotate_on_shutdown),
            ("flush_hourly", flush_hourly),
            ("flush_daily", flush_daily),
            ("hour", hour),
            ("minute", minute),
            ("rotate_on_daily_flush", rotate_on_daily_flush),
            ("paths", paths),
            ("services", services),
        )
        if value is not None
    }
    _check_overrides(overrides)
    args = dict(overrides, apply=apply)

    async def build() -> PlanSpec:
        # setSettings requires the full config object; only getSettings adds the
        # read-only `status` field, which the config datamodel rejects.
        current = await get_object(state, "WriteCache", "getSettings", {})
        before = {key: value for key, value in current.items() if key != "status"}
        after = dict(before)
        after.update(overrides)
        # Mirror WriteCache.setSettings normalization so the plan matches what
        # is stored, then applied by the writecache module.
        if after.get("use_tmpfs"):
            after["flush_on_boot"] = False
            after["sharedfolderref"] = ""
        else:
            after["tmpfs_size"] = "0%"
            if not after.get("sharedfolderref"):
                raise ValueError("sharedfolderref is required when use_tmpfs is false")
        for key in ("paths", "services"):
            if key in after:
                after[key] = _normalize_entries(str(after[key]))
        side_effects = {
            "config": "settings are stored in config.xml; config_apply writecache deploys them"
        }
        if before.get("use_tmpfs") != after.get("use_tmpfs") or before.get(
            "ram_backing"
        ) != after.get("ram_backing"):
            side_effects["workspace"] = (
                "the current writecache workspace is unmounted before the backing change is deployed"
            )
        return PlanSpec(
            rpc_calls=[{"service": "WriteCache", "method": "setSettings", "params": after}],
            before=before,
            after=after,
            changes=[
                {"field": key, "before": before.get(key), "after": after.get(key)}
                for key in _SETTINGS_KEYS
                if before.get(key) != after.get(key)
            ],
            side_effects=side_effects,
            modules_expected={"writecache"},
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        return ExecutionOutcome(
            result=await state.backend.call(
                "WriteCache", "setSettings", plan.rpc_calls[0]["params"]
            )
        )

    return await guarded_write(
        ctx=ctx,
        tool="writecache_set",
        tier=Tier.OPERATOR,
        args=args,
        build=build,
        execute=execute,
        confirm_token=confirm_token,
        apply=apply,
    )


async def writecache_flush(
    ctx: Context, rotate: bool = False, confirm_token: str | None = None
) -> PlanResponse | OperationResult:
    state = get_state(ctx)
    params = {"rotate": rotate}

    async def build() -> PlanSpec:
        return PlanSpec(
            rpc_calls=[{"service": "WriteCache", "method": "doFlush", "params": params}],
            before=None,
            after={"flushed": True, "rotate": rotate},
            changes=[{"field": "writecache", "before": None, "after": "flushed"}],
        )

    async def execute(plan: PlanSpec) -> ExecutionOutcome:
        job = await state.jobs.start("WriteCache", "doFlush", plan.rpc_calls[0]["params"])
        result = await state.jobs.wait(job, state.settings.job_timeout_seconds, ctx)
        return ExecutionOutcome(
            result=result.model_dump(),
            job_id=job if result.running else None,
        )

    return await guarded_write(
        ctx=ctx,
        tool="writecache_flush",
        tier=Tier.OPERATOR,
        args={"rotate": rotate},
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
    op(
        "writecache_set",
        writecache_set,
        "Update writecache settings; unspecified settings are kept and the writecache module is marked dirty.",
        "WriteCache.getSettings",
        "WriteCache.setSettings",
    ),
    op(
        "writecache_flush",
        writecache_flush,
        "Flush the writecache; rotate=True rotates the backing files instead.",
        "WriteCache.doFlush",
        idempotent=False,
    ),
)
