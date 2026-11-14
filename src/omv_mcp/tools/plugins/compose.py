from __future__ import annotations

from typing import Any, Literal

from fastmcp import Context

from omv_mcp.models import Page
from omv_mcp.rpc.redact import redact, redact_text
from omv_mcp.tools._common import get_state, list_call, normalize_list, rpc_call_list, rpc_call_ro
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


async def compose_file_get(
    ctx: Context, uuid: str | None = None, name: str | None = None
) -> dict[str, Any]:
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
        return {"uuid": uuid, "name": result.get("name", name), "content": redact_text(str(body))}
    return {"uuid": uuid, "name": name, "content": redact_text(str(result))}


async def compose_containers(ctx: Context) -> Any:
    state = get_state(ctx)
    result = await rpc_call_list(state, "Compose", "getContainerList")
    _, rows = normalize_list(result)
    return redact(rows)


async def compose_container_log(ctx: Context, uuid: str, tail: int = 200) -> dict[str, Any]:
    state = get_state(ctx)
    result = await rpc_call_ro(state, "Compose", "getContainerLog", {"uuid": uuid, "tail": tail})
    return {"uuid": uuid, "content": redact_text(str(result))}


async def compose_stats(ctx: Context) -> Any:
    state = get_state(ctx)
    result = await rpc_call_list(state, "Compose", "getContainerList")
    _, rows = normalize_list(result)
    keep = {"name", "state", "status", "cpu", "memory", "mem", "pids", "netio", "blockio"}
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
        "Return recent container logs.",
        "Compose.getContainerLog",
    ),
    ro(
        "compose_stats",
        compose_stats,
        "Return container resource statistics.",
        "Compose.getContainerList",
    ),
)
