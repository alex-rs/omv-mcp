from __future__ import annotations

import hmac
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, AuthProvider, TokenVerifier

from omv_mcp import __version__
from omv_mcp.rpc.errors import OmvRpcError
from omv_mcp.rpc.redact import redact_text
from omv_mcp.safety.guard import SafetyError
from omv_mcp.settings import Settings
from omv_mcp.state import AppState, make_backend
from omv_mcp.tools.registry import ALL_PLUGIN_PACKAGES, Tier, iter_tools

INSTRUCTIONS = (
    "OMV writes only change config.xml and mark modules dirty. Call config_pending, "
    "then config_apply with the exact dirty modules you intend to deploy; never apply "
    "modules you did not dirty. Every mutating tool first returns a plan; re-call it "
    "with confirm_token to execute. Read-only tools never change state. Inspect before changing."
)


def wrap_errors(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    import functools

    @functools.wraps(fn)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except (OmvRpcError, SafetyError, ValueError) as exc:
            raise ToolError(redact_text(str(exc))) from exc

    return wrapped


def _lifespan(settings: Settings, backend: Any) -> Callable[[FastMCP], Any]:
    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, AppState]]:
        state = AppState.create(settings, backend=backend)
        try:
            yield {"state": state}
        finally:
            await state.backend.close()

    return lifespan


class BearerTokenVerifier(TokenVerifier):
    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    async def verify_token(self, token: str) -> AccessToken | None:
        if hmac.compare_digest(token, self._token):
            return AccessToken(
                token=token,
                client_id="omv-mcp",
                scopes=["omv"],
                expires_at=None,
            )
        return None


async def probe_plugins(settings: Settings) -> frozenset[str]:
    backend = make_backend(settings)
    packages: set[str] = set()
    try:
        result = await backend.call("Plugin", "getList", {"start": 0, "limit": 500})
        rows: list[dict[str, Any]] = []
        if isinstance(result, dict) and isinstance(result.get("data"), list):
            rows = [row for row in result["data"] if isinstance(row, dict)]
        elif isinstance(result, list):
            rows = [row for row in result if isinstance(row, dict)]
        for row in rows:
            name = str(row.get("name") or row.get("package") or "")
            if name in ALL_PLUGIN_PACKAGES.values():
                packages.add(name)
        if not packages:
            probes = {
                "openmediavault-mergerfs": ("Mergerfs", "getList"),
                "openmediavault-snapraid": ("SnapRaid", "getVersion"),
                "openmediavault-writecache": ("WriteCache", "getSettings"),
                "openmediavault-compose": ("Compose", "get"),
                "openmediavault-wireguard": ("Wireguard", "getTunnelList"),
                "openmediavault-omvextrasorg": ("omvextras", "get"),
            }
            for package, (service, method) in probes.items():
                try:
                    await backend.call(service, method)
                    packages.add(package)
                except Exception:
                    continue
    finally:
        await backend.close()
    return frozenset(packages)


def build_server(
    settings: Settings,
    *,
    plugins: frozenset[str] = frozenset(),
    backend: Any = None,
    auth: AuthProvider | None = None,
) -> FastMCP:
    mcp = FastMCP(
        name="omv-mcp",
        version=__version__,
        instructions=INSTRUCTIONS,
        lifespan=_lifespan(settings, backend),
        auth=auth,
    )
    for spec in iter_tools(plugins):
        if spec.name == "system_power" and not settings.allow_power:
            continue
        if spec.tier > settings.mode_tier:
            continue
        mcp.tool(
            name=spec.name,
            description=spec.description,
            annotations=spec.annotations,
            tags={Tier(spec.tier).name.lower()},
        )(wrap_errors(spec.fn))

    from omv_mcp.prompts import register_prompts
    from omv_mcp.resources import register_resources

    register_resources(mcp)
    register_prompts(mcp)
    return mcp


def bearer_from_settings(settings: Settings) -> BearerTokenVerifier | None:
    if settings.http_token is None:
        return None
    return BearerTokenVerifier(settings.http_token.get_secret_value())


def validate_http_bind(settings: Settings) -> None:
    parsed = urlparse(f"//{settings.http_bind_host}")
    host = parsed.hostname or settings.http_bind_host
    if (
        settings.transport.value == "http"
        and host not in {"127.0.0.1", "localhost", "::1"}
        and not settings.http_token
    ):
        raise ValueError("non-loopback HTTP bind requires OMV_MCP_HTTP_TOKEN")
