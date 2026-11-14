from __future__ import annotations

from typing import Any, Literal

from fastmcp import Context

from omv_mcp.models import Page
from omv_mcp.rpc.redact import redact, redact_text
from omv_mcp.tools._common import (
    cap_payload,
    get_state,
    list_call,
    normalize_list,
    rpc_call_list,
    rpc_call_ro,
)
from omv_mcp.tools.registry import ro


async def compose_files_list(
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
        "Compose",
        "getFileList",
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        order=order,
        fields=fields,
        ctx=ctx,
    )


async def compose_file_get(ctx: Context, uuid: str | None = None, name: str | None = None) -> Any:
    state = get_state(ctx)
    if uuid is None:
        files = await rpc_call_list(state, "Compose", "getFileList")
        rows = files.get("data", []) if isinstance(files, dict) else []
        match = next(
            (row for row in rows if isinstance(row, dict) and row.get("name") == name),
            None,
        )
        if not match:
            raise ValueError(f"compose file {name!r} not found")
        uuid = str(match["uuid"])
    result = await rpc_call_ro(state, "Compose", "getFile", {"uuid": uuid})
    if isinstance(result, dict):
        body = result.get("body") or result.get("content") or ""
        output = {"uuid": uuid, "name": result.get("name", name), "content": redact_text(str(body))}
    else:
        output = {"uuid": uuid, "name": name, "content": redact_text(str(result))}
    return cap_payload(output, state.settings.response_max_bytes)


async def compose_containers(ctx: Context) -> Any:
    state = get_state(ctx)
    result = await rpc_call_list(state, "Compose", "getContainerList")
    _, rows = normalize_list(result)
    # execurl embeds a short-lived cterm HMAC credential; do not expose it.
    return redact([{k: v for k, v in row.items() if k != "execurl"} for row in rows])


async def compose_container_log(ctx: Context, id: str, name: str, tail: int = 200) -> Any:
    state = get_state(ctx)
    data = await state.backend.fetch_file("Compose", "getContainerLog", {"id": id, "name": name})
    text = redact_text(data.decode("utf-8", "replace"))
    lines = text.splitlines()[-max(1, min(tail, 5000)) :]
    return cap_payload(
        {"id": id, "name": name, "lines": len(lines), "content": "\n".join(lines)},
        state.settings.response_max_bytes,
    )


async def compose_stats(ctx: Context) -> Any:
    state = get_state(ctx)
    result = await rpc_call_list(state, "Compose", "getContainerList")
    _, rows = normalize_list(result)
    keep = {"id", "name", "image", "state", "status", "running", "created"}
    return redact([{k: v for k, v in row.items() if k in keep} for row in rows])


TOOLS = (
    ro("compose_files_list", compose_files_list, "List compose files.", "Compose.getFileList"),
    ro(
        "compose_file_get",
        compose_file_get,
        "Return a compose file with secrets redacted.",
        "Compose.getFile",
    ),
    ro(
        "compose_containers",
        compose_containers,
        "List compose containers.",
        "Compose.getContainerList",
    ),
    ro(
        "compose_container_log",
        compose_container_log,
        "Return recent logs for a container id/name.",
        "Compose.getContainerLog",
    ),
    ro(
        "compose_stats",
        compose_stats,
        "Return compact container status.",
        "Compose.getContainerList",
    ),
)
