from __future__ import annotations

import asyncio
import contextlib
import json
import posixpath
import shlex
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import asyncssh

from omv_mcp.omv import OMV_RPC_PATH
from omv_mcp.rpc.errors import OmvRpcError
from omv_mcp.rpc.redact import redact_text
from omv_mcp.settings import Settings


def build_command(
    rpc_user: str, service: str, method: str, params: Mapping[str, Any] | None = None
) -> str:
    payload = json.dumps(dict(params or {}), separators=(",", ":"))
    return shlex.join([OMV_RPC_PATH, "-u", rpc_user, service, method, payload])


def _decode(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def _as_bytes(value: bytes | str | None) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    return value.encode("utf-8")


def _parse_omv_output(stdout: str, stderr: str, exit_status: int = 0) -> Any:
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for text in (stdout, stderr):
        try:
            whole = json.loads(text.strip())
        except json.JSONDecodeError:
            whole = None
        if isinstance(whole, dict):
            candidates.append(whole)
            continue
        if whole is not None or text.strip() == "null":
            return whole
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and ("response" in parsed or "error" in parsed):
                candidates.append(parsed)
    for parsed in reversed(candidates):
        if "response" not in parsed and "error" not in parsed:
            return parsed
        if "error" in parsed:
            error = parsed.get("error") or {}
            if isinstance(error, dict):
                raise OmvRpcError(
                    redact_text(str(error.get("message") or "OMV RPC failed")),
                    code=error.get("code") if isinstance(error.get("code"), int) else None,
                    trace=str(error["trace"]) if error.get("trace") else None,
                )
            raise OmvRpcError(redact_text(str(error)))
        if "response" in parsed:
            return parsed["response"]
    lines = [line.strip() for line in (stdout + "\n" + stderr).splitlines() if line.strip()]
    if not lines and exit_status == 0:
        return None
    detail = lines[-1] if lines else "empty output"
    raise OmvRpcError(redact_text(detail))


class SshBackend:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._conn: asyncssh.SSHClientConnection | None = None
        self._lock = asyncio.Lock()

    async def _ensure_connection(self) -> asyncssh.SSHClientConnection:
        if self._conn is not None:
            return self._conn
        async with self._lock:
            if self._conn is not None:
                return self._conn  # type: ignore[unreachable]
            kwargs: dict[str, Any] = {
                "host": self._settings.ssh_host,
                "port": self._settings.ssh_port,
                "username": self._settings.ssh_user,
            }
            if self._settings.ssh_key:
                kwargs["client_keys"] = [str(self._settings.ssh_key)]
            if self._settings.ssh_known_hosts:
                kwargs["known_hosts"] = str(self._settings.ssh_known_hosts)
            else:
                kwargs["known_hosts"] = ()
            self._conn = await asyncssh.connect(**kwargs)
            return self._conn

    async def _discard(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            conn.close()
            with contextlib.suppress(Exception):
                await conn.wait_closed()

    async def _run_command(
        self, command: str, *, timeout: float | None = None
    ) -> asyncssh.SSHCompletedProcess:
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                conn = await self._ensure_connection()
                return await conn.run(command, check=False, timeout=timeout)
            except (asyncssh.Error, OSError, ConnectionError) as exc:
                last_error = exc
                await self._discard()
                if attempt:
                    break
        assert last_error is not None
        raise OmvRpcError(redact_text(str(last_error)))

    async def call(
        self,
        service: str,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        command = build_command(self._settings.rpc_user, service, method, params)
        result = await self._run_command(command, timeout=timeout)
        try:
            return _parse_omv_output(
                _decode(result.stdout), _decode(result.stderr), result.exit_status or 0
            )
        except OmvRpcError as exc:
            exc.service, exc.method = service, method
            raise

    async def fetch_file(
        self,
        service: str,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> bytes:
        response = await self.call(service, method, params, timeout=timeout)
        if not isinstance(response, dict):
            raise OmvRpcError(f"{service}.{method} did not return a filepath")
        filepath = response.get("filepath")
        if not isinstance(filepath, str) or not posixpath.isabs(filepath):
            raise OmvRpcError(f"{service}.{method} returned an unsafe filepath")
        if ".." in Path(filepath).parts:
            raise OmvRpcError(f"{service}.{method} returned an unsafe filepath")
        if service == "Rrd" and not filepath.endswith(".png"):
            raise OmvRpcError("Rrd.fetch_file only allows PNG graphs")
        if service == "LogFile" and not filepath.startswith("/tmp/"):
            raise OmvRpcError("LogFile.fetch_file only allows /tmp files")
        if service not in {"Rrd", "LogFile"}:
            raise OmvRpcError(f"fetch_file is not allowed for service {service}")
        result = await self._run_command(f"cat {shlex.quote(filepath)}", timeout=timeout)
        if result.exit_status != 0:
            raise OmvRpcError(redact_text(_decode(result.stderr) or "cannot read remote file"))
        if response.get("unlink") is True:
            await self._run_command(f"rm -f {shlex.quote(filepath)}", timeout=timeout)
        return _as_bytes(result.stdout)

    async def close(self) -> None:
        await self._discard()
