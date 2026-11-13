from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from typing import Any

import httpx

from omv_mcp.rpc.errors import OmvRpcError
from omv_mcp.rpc.redact import redact_text
from omv_mcp.settings import Settings

_SESSION_RE = re.compile(r"(?i)session (not authenticated|expired)")
_SESSION_HEADER = "X-OPENMEDIAVAULT-SESSIONID"


class HttpBackend:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._sessionid: str | None = None
        base = (settings.http_url or "").rstrip("/") + "/"
        verify: bool | str = True
        if settings.tls_ca:
            verify = str(settings.tls_ca)
        elif not settings.tls_verify:
            verify = False
        self._client = httpx.AsyncClient(
            base_url=base,
            verify=verify,
            timeout=httpx.Timeout(60.0),
            follow_redirects=True,
        )
        self._login_lock = asyncio.Lock()

    def _body(self, service: str, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        return {"service": service, "method": method, "params": dict(params or {})}

    def _headers(self) -> dict[str, str]:
        return {_SESSION_HEADER: self._sessionid} if self._sessionid else {}

    async def _login(self) -> None:
        async with self._login_lock:
            if self._sessionid:
                return
            for attempt in range(2):
                response = await self._client.post(
                    "rpc.php",
                    json={
                        "service": "Session",
                        "method": "login",
                        "params": {
                            "username": self._settings.http_username,
                            "password": self._settings.http_password.get_secret_value()
                            if self._settings.http_password
                            else "",
                        },
                    },
                )
                if response.status_code == 429 and attempt == 0:
                    await asyncio.sleep(1)
                    continue
                if response.status_code >= 400:
                    raise OmvRpcError(
                        f"HTTP login failed with status {response.status_code}",
                        code=response.status_code,
                        service="Session",
                        method="login",
                    )
                payload = response.json()
                if payload.get("error"):
                    error = payload["error"]
                    raise OmvRpcError(
                        redact_text(str(error.get("message") or "login failed")),
                        code=error.get("code"),
                        service="Session",
                        method="login",
                        trace=error.get("trace"),
                    )
                data = payload.get("response") or {}
                status = data.get("status")
                if status == "challengeRequired":
                    raise OmvRpcError(
                        f"MFA is enabled for {self._settings.http_username}; "
                        "use the SSH backend or a non-MFA admin user",
                        service="Session",
                        method="login",
                    )
                sessionid = data.get("sessionid")
                if not isinstance(sessionid, str) or not sessionid:
                    raise OmvRpcError(
                        "login response did not contain a sessionid",
                        service="Session",
                        method="login",
                    )
                self._sessionid = sessionid
                return
            raise OmvRpcError("login rate limited", service="Session", method="login")

    async def _relogin(self) -> None:
        self._sessionid = None
        await self._login()

    @staticmethod
    def _needs_relogin(response: httpx.Response, payload: Any) -> bool:
        if response.status_code == 401:
            return True
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                if error.get("code") == 401:
                    return True
                if _SESSION_RE.search(str(error.get("message") or "")):
                    return True
        return False

    async def _post(
        self,
        path: str,
        service: str,
        method: str,
        params: Mapping[str, Any] | None,
        timeout: float | None,
        *,
        raw: bool = False,
    ) -> httpx.Response:
        await self._login()
        kwargs: dict[str, Any] = {
            "json": self._body(service, method, params),
            "headers": self._headers(),
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        response = await self._client.post(path, **kwargs)
        if raw:
            if self._needs_relogin(response, _safe_json(response)):
                await self._relogin()
                kwargs["headers"] = self._headers()
                response = await self._client.post(path, **kwargs)
            return response
        payload = _safe_json(response)
        if self._needs_relogin(response, payload):
            await self._relogin()
            kwargs["headers"] = self._headers()
            response = await self._client.post(path, **kwargs)
            payload = _safe_json(response)
        if response.status_code >= 400:
            raise OmvRpcError(
                f"HTTP {response.status_code}",
                code=response.status_code,
                service=service,
                method=method,
            )
        _raise_on_error(payload, service, method)
        return response

    async def call(
        self,
        service: str,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        response = await self._post("rpc.php", service, method, params, timeout)
        payload = _safe_json(response)
        return payload.get("response")

    async def fetch_file(
        self,
        service: str,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> bytes:
        response = await self._post("download.php", service, method, params, timeout, raw=True)
        if response.status_code >= 400:
            raise OmvRpcError(
                f"HTTP {response.status_code}",
                code=response.status_code,
                service=service,
                method=method,
            )
        return response.content

    async def close(self) -> None:
        await self._client.aclose()


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return None


def _raise_on_error(payload: Any, service: str, method: str) -> None:
    if isinstance(payload, dict) and payload.get("error"):
        error = payload["error"]
        raise OmvRpcError(
            redact_text(str(error.get("message") or "OMV RPC failed")),
            code=error.get("code"),
            service=service,
            method=method,
            trace=error.get("trace"),
        )
