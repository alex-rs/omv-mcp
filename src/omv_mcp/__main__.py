from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from omv_mcp.server import build_server, probe_plugins, validate_http_bind
from omv_mcp.settings import Backend, Mode, Settings, Transport


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="omv-mcp", description="Safe MCP server for OpenMediaVault 8")
    p.add_argument("--mode", choices=[m.value for m in Mode])
    p.add_argument("--backend", choices=[b.value for b in Backend])
    p.add_argument("--host", dest="ssh_host")
    p.add_argument("--port", dest="ssh_port", type=int)
    p.add_argument("--ssh-user", dest="ssh_user")
    p.add_argument("--ssh-key", dest="ssh_key")
    p.add_argument("--ssh-known-hosts", dest="ssh_known_hosts")
    p.add_argument("--rpc-user", dest="rpc_user")
    p.add_argument("--url", dest="http_url")
    p.add_argument("--http-username", dest="http_username")
    p.add_argument("--http-password", dest="http_password")
    p.add_argument("--tls-verify", dest="tls_verify", action="store_true", default=None)
    p.add_argument("--no-tls-verify", dest="tls_verify", action="store_false", default=None)
    p.add_argument("--tls-ca", dest="tls_ca")
    p.add_argument("--transport", choices=[t.value for t in Transport])
    p.add_argument("--http-bind-host", dest="http_bind_host")
    p.add_argument("--http-bind-port", dest="http_bind_port", type=int)
    p.add_argument("--http-token", dest="http_token")
    p.add_argument("--allow-power", dest="allow_power", action="store_true", default=None)
    p.add_argument("--no-allow-power", dest="allow_power", action="store_false", default=None)
    p.add_argument("--audit-path", dest="audit_path")
    p.add_argument("--log-level", dest="log_level")
    return p


def settings_from_args(args: argparse.Namespace) -> Settings:
    values = {key: value for key, value in vars(args).items() if value is not None}
    return Settings(**values)


def main() -> None:
    args = parser().parse_args()
    settings = settings_from_args(args)
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    validate_http_bind(settings)

    if settings.transport is Transport.HTTP:
        from omv_mcp.server import bearer_from_settings

        auth = bearer_from_settings(settings)
    else:
        auth = None

    try:
        plugins = asyncio.run(probe_plugins(settings))
    except Exception as exc:
        print(f"omv-mcp: cannot probe OMV plugins: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    server = build_server(settings, plugins=plugins, auth=auth)
    if settings.transport is Transport.HTTP:
        server.run(
            transport="http",
            host=settings.http_bind_host,
            port=settings.http_bind_port,
        )
    else:
        server.run()


if __name__ == "__main__":
    main()
