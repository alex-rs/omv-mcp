from __future__ import annotations

import contextlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastmcp import Context

from omv_mcp.models import Change, OperationResult, Page, PlanResponse
from omv_mcp.rpc.redact import redact
from omv_mcp.safety.guard import SafetyError, is_never_exposed
from omv_mcp.shaping import filter_sort_slice, project_fields, shape_page
from omv_mcp.state import AppState


def get_state(ctx: Context) -> AppState:
    state = ctx.lifespan_context.get("state")
    if not isinstance(state, AppState):
        raise RuntimeError("omv-mcp state is not initialized")
    return state


async def rpc_call_ro(
    state: AppState,
    service: str,
    method: str,
    params: Mapping[str, Any] | None = None,
    *,
    timeout: float | None = None,
) -> Any:
    if is_never_exposed(service, method):
        raise SafetyError(f"RPC {service}.{method} is never exposed")
    return await state.backend.call(service, method, params, timeout=timeout)


async def rpc_call_list(
    state: AppState,
    service: str,
    method: str,
    params: Mapping[str, Any] | None = None,
) -> Any:
    payload = dict(params or {})
    payload.setdefault("start", 0)
    payload.setdefault("limit", -1)
    return await rpc_call_ro(state, service, method, payload)


def normalize_list(result: Any) -> tuple[int, list[dict[str, Any]]]:
    if isinstance(result, dict):
        data = result.get("data")
        if isinstance(data, list):
            total = result.get("total")
            return (
                int(total) if isinstance(total, int) else len(data),
                [item for item in data if isinstance(item, dict)],
            )
        return 1, [dict(result)]
    if isinstance(result, list):
        rows = [item for item in result if isinstance(item, dict)]
        return len(result), rows
    return 0, []


async def list_call(
    state: AppState,
    service: str,
    method: str,
    *,
    params: Mapping[str, Any] | None = None,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    sort: str | None = None,
    order: str = "asc",
    fields: Sequence[str] | str | None = None,
    ctx: Context | None = None,
    native_paging: bool = False,
    row_filter: Callable[[dict[str, Any]], bool] | None = None,
) -> Page[dict[str, Any]]:
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    call_params = dict(params or {})
    if native_paging:
        call_params["start"] = offset
        call_params["limit"] = limit
        if search:
            call_params["search"] = search
        if sort:
            call_params["sortfield"] = sort
            call_params["sortdir"] = order
        result = await rpc_call_ro(state, service, method, call_params)
        total, rows = normalize_list(result)
        sliced = rows
    else:
        call_params.setdefault("start", 0)
        call_params.setdefault("limit", -1)
        result = await rpc_call_ro(state, service, method, call_params)
        _, rows = normalize_list(result)
        if row_filter is not None:
            rows = [row for row in rows if row_filter(row)]
        total, sliced = filter_sort_slice(
            rows,
            search=search,
            sort=sort,
            order=order,
            limit=limit,
            offset=offset,
        )
    projected = [redact(project_fields(row, fields)) for row in sliced]
    page = shape_page(
        projected,
        total=total,
        offset=offset,
        limit=limit,
        max_bytes=state.settings.response_max_bytes,
    )
    if ctx is not None:
        with contextlib.suppress(Exception):
            await ctx.report_progress(progress=page.count, total=page.total)
    return page


async def dirty_modules(state: AppState) -> list[str]:
    result = await state.backend.call("System", "getInformation")
    if not isinstance(result, dict):
        return []
    dirty = result.get("dirtyModules", [])
    if isinstance(dirty, dict):
        return sorted(str(key) for key in dirty)
    if isinstance(dirty, list):
        return sorted(str(item) for item in dirty if item)
    return []


def cap_payload(value: Any, max_bytes: int) -> Any:
    text = json.dumps(value, default=str)
    if len(text.encode()) <= max_bytes:
        return value
    return {
        "truncated": True,
        "note": "response capped; narrow the request",
        "preview": text[: max_bytes // 2],
    }


def result_page(result: Any, *, fields: Sequence[str] | str | None = None) -> Any:
    if isinstance(result, dict):
        return redact(project_fields(result, fields))
    return redact(result)


async def get_object(
    state: AppState, service: str, method: str, params: Mapping[str, Any]
) -> dict[str, Any]:
    result = await rpc_call_ro(state, service, method, params)
    if not isinstance(result, dict):
        raise ValueError(f"{service}.{method} did not return an object")
    return result


@dataclass
class ExecutionOutcome:
    result: Any = None
    job_id: str | None = None


@dataclass
class PlanSpec:
    rpc_calls: list[dict[str, Any]]
    before: Any
    after: Any
    changes: list[dict[str, Any]]
    side_effects: dict[str, Any] = field(default_factory=dict)
    dirty_before: list[str] = field(default_factory=list)
    modules_expected: set[str] = field(default_factory=set)
    before_fingerprint: str = "null"
    recheck: Callable[[], Awaitable[Any]] | None = None


def _fingerprint(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat()


async def _elicit(ctx: Context, tool: str) -> None:
    try:
        response = await ctx.elicit(
            f"Execute {tool}? This is an admin-tier mutation.",
            ["accept", "decline"],
        )
    except Exception:
        return
    if type(response).__name__ == "DeclinedElicitation":
        raise SafetyError("rejected by user")
    if type(response).__name__ == "CancelledElicitation":
        raise SafetyError("rejected by user")
    data = getattr(response, "data", None)
    if data == "decline":
        raise SafetyError("rejected by user")


async def guarded_write(
    *,
    ctx: Context,
    tool: str,
    tier: int,
    args: dict[str, Any],
    build: Callable[[], Awaitable[PlanSpec]],
    execute: Callable[[PlanSpec], Awaitable[ExecutionOutcome]],
    confirm_token: str | None,
    apply: bool = False,
    refresh_dirty: bool = True,
) -> PlanResponse | OperationResult:
    state = get_state(ctx)
    before_dirty = await dirty_modules(state)

    if confirm_token is None:
        new_plan = await build()
        new_plan.dirty_before = before_dirty
        new_plan.before_fingerprint = (
            _fingerprint(new_plan.before) if new_plan.before is not None else "null"
        )
        if apply and new_plan.dirty_before:
            raise SafetyError(
                "apply=True refused: modules already dirty before this call: "
                f"{new_plan.dirty_before}"
            )
        token, expiry = await state.confirm.issue(tool, args, new_plan)
        response = PlanResponse(
            tool=tool,
            rpc_calls=[redact(call) for call in new_plan.rpc_calls],
            before=redact(new_plan.before),
            after=redact(new_plan.after),
            changes=[Change(**change) for change in new_plan.changes],
            side_effects=redact(new_plan.side_effects),
            dirty_modules=new_plan.dirty_before,
            modules_expected=sorted(new_plan.modules_expected),
            confirm_token=token,
            expires_at=_iso(expiry),
        )
        await state.audit.write(
            {
                "tool": tool,
                "tier": tier,
                "args": redact(args),
                "rpc_calls": response.rpc_calls,
                "status": "plan",
                "result": {"dirty_modules": new_plan.dirty_before},
                "error": None,
                "job_id": None,
                "dirtied_modules": [],
                "pending_apply": new_plan.dirty_before,
            }
        )
        return response

    plan: PlanSpec = await state.confirm.consume(confirm_token, tool, args)
    current_dirty = await dirty_modules(state)
    if current_dirty != plan.dirty_before:
        raise SafetyError(
            f"dirty modules changed since the plan: before={plan.dirty_before} now={current_dirty}"
        )
    if plan.recheck is not None:
        current = await plan.recheck()
        if _fingerprint(current) != plan.before_fingerprint:
            raise SafetyError("the target changed since the plan was issued")

    # Build closures (e.g. merged update params) are populated during the plan
    # phase. Re-run build on execute so the confirmed call uses the same state,
    # without changing the token-bound plan itself.
    rebuilt = await build()
    if rebuilt.before is not None and _fingerprint(rebuilt.before) != plan.before_fingerprint:
        raise SafetyError("the target changed since the plan was issued")

    from omv_mcp.safety.modes import Tier

    if state.settings.elicit_admin and tier is Tier.ADMIN:
        await _elicit(ctx, tool)

    await state.limiter.acquire()
    try:
        async with state.write_lock:
            outcome = await execute(plan)
            after_dirty = await dirty_modules(state) if refresh_dirty else plan.dirty_before
            dirtied = sorted(set(after_dirty) - set(plan.dirty_before))
            if (
                refresh_dirty
                and plan.modules_expected
                and not set(dirtied) <= plan.modules_expected
            ):
                raise SafetyError(
                    "mutation dirtied unexpected modules: "
                    f"expected={sorted(plan.modules_expected)} dirtied={dirtied}"
                )
            applied: list[str] = []
            if apply:
                if plan.dirty_before:
                    raise SafetyError(
                        "apply=True refused: modules already dirty before this call: "
                        f"{plan.dirty_before}"
                    )
                if not dirtied:
                    raise SafetyError("no OMV config module was dirtied")
                applied_result = await state.backend.call(
                    "Config",
                    "applyChanges",
                    {"modules": dirtied, "force": False},
                    timeout=300,
                )
                applied = (
                    [str(item) for item in applied_result]
                    if isinstance(applied_result, list)
                    else dirtied
                )
                after_dirty = await dirty_modules(state)
        result = OperationResult(
            tool=tool,
            result=redact(outcome.result),
            job_id=outcome.job_id,
            dirty_modules=after_dirty,
            dirtied_modules=dirtied,
            pending_apply=after_dirty,
            applied_modules=applied,
            next_step=(
                "call config_apply with the exact dirty modules"
                if after_dirty
                else "no pending config changes"
            ),
        )
        await state.audit.write(
            {
                "tool": tool,
                "tier": tier,
                "args": redact(args),
                "rpc_calls": redact(plan.rpc_calls),
                "status": "ok",
                "result": result.model_dump(),
                "error": None,
                "job_id": outcome.job_id,
                "dirtied_modules": dirtied,
                "pending_apply": after_dirty,
            }
        )
        return result
    except Exception as exc:
        pending = current_dirty
        dirtied_on_error: list[str] = []
        if refresh_dirty:
            try:
                refreshed = await dirty_modules(state)
            except Exception:
                refreshed = None
            if refreshed is not None:
                pending = refreshed
                dirtied_on_error = sorted(set(pending) - set(plan.dirty_before))
        await state.audit.write(
            {
                "tool": tool,
                "tier": tier,
                "args": redact(args),
                "rpc_calls": redact(plan.rpc_calls),
                "status": "error",
                "result": None,
                "error": redact(str(exc)),
                "job_id": None,
                "dirtied_modules": dirtied_on_error,
                "pending_apply": pending,
            }
        )
        raise
