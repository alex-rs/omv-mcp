from __future__ import annotations

import json

from fastmcp import Context, FastMCP

from omv_mcp.rpc.redact import redact, redact_text
from omv_mcp.schemas import read_catalog, read_schema
from omv_mcp.tools._common import dirty_modules, get_state, rpc_call_ro


def register_resources(mcp: FastMCP) -> None:
    @mcp.resource("omv://system/info", mime_type="application/json")
    async def system_info_resource(ctx: Context) -> str:
        state = get_state(ctx)
        return json.dumps(redact(await rpc_call_ro(state, "System", "getInformation")), default=str)

    @mcp.resource("omv://storage/health", mime_type="application/json")
    async def storage_health_resource(ctx: Context) -> str:
        from omv_mcp.tools.storage import storage_health_summary

        return json.dumps((await storage_health_summary(ctx)).model_dump(), default=str)

    @mcp.resource("omv://config/pending", mime_type="application/json")
    async def config_pending_resource(ctx: Context) -> str:
        state = get_state(ctx)
        modules = await dirty_modules(state)
        return json.dumps({"dirty": bool(modules), "modules": modules})

    @mcp.resource("omv://logs/{name}", mime_type="text/plain")
    async def log_resource(name: str, ctx: Context) -> str:
        state = get_state(ctx)
        data = await state.backend.fetch_file("LogFile", "getContent", {"id": name})
        return redact_text(data.decode("utf-8", "replace"))[-20000:]

    @mcp.resource("omv://rpc/catalog", mime_type="application/json")
    async def catalog_resource(ctx: Context) -> str:
        return json.dumps(read_catalog(), indent=2)

    @mcp.resource("omv://rpc/schema/{service}", mime_type="application/json")
    async def schema_resource(service: str, ctx: Context) -> str:
        schema = read_schema(service)
        if schema is None:
            return json.dumps({"service": service, "schema": None})
        return json.dumps(schema, indent=2)
