from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from omv_mcp.rpc.errors import OmvRpcError
from omv_mcp.rpc.http import HttpBackend
from omv_mcp.settings import Settings


def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("OMV_MCP_BACKEND", "http")
    monkeypatch.setenv("OMV_MCP_HTTP_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("OMV_MCP_HTTP_PASSWORD", "adminpw")
    return Settings()


def body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)  # type: ignore[no-any-return]


@respx.mock
async def test_login_and_session_header(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = body(request)
        seen.append(payload)
        if payload["method"] == "login":
            return httpx.Response(
                200, json={"response": {"status": "authenticated", "sessionid": "s1"}}
            )
        assert request.headers["X-OPENMEDIAVAULT-SESSIONID"] == "s1"
        return httpx.Response(200, json={"response": {"hostname": "omv-test"}})

    respx.post("http://127.0.0.1:8080/rpc.php").mock(side_effect=handler)
    backend = HttpBackend(settings(monkeypatch))
    assert await backend.call("System", "getInformation") == {"hostname": "omv-test"}
    assert seen[0]["service"] == "Session"
    await backend.close()


@respx.mock
async def test_close_logs_out(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = body(request)
        calls.append(payload["method"])
        if payload["method"] == "login":
            return httpx.Response(
                200, json={"response": {"status": "authenticated", "sessionid": "s1"}}
            )
        return httpx.Response(200, json={"response": None})

    respx.post("http://127.0.0.1:8080/rpc.php").mock(side_effect=handler)
    backend = HttpBackend(settings(monkeypatch))
    await backend.call("System", "getInformation")
    await backend.close()
    assert calls == ["login", "getInformation", "logout"]


@respx.mock
async def test_challenge_required(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.post("http://127.0.0.1:8080/rpc.php").mock(
        return_value=httpx.Response(200, json={"response": {"status": "challengeRequired"}})
    )
    backend = HttpBackend(settings(monkeypatch))
    with pytest.raises(OmvRpcError, match="MFA is enabled for admin"):
        await backend.call("System", "noop")
    await backend.close()


@respx.mock
async def test_401_relogin_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = body(request)
        calls.append(payload["method"])
        if payload["method"] == "login":
            return httpx.Response(
                200, json={"response": {"status": "authenticated", "sessionid": "s2"}}
            )
        if calls.count("noop") == 1:
            return httpx.Response(401, json={"error": {"code": 401, "message": "Session expired."}})
        return httpx.Response(200, json={"response": True})

    respx.post("http://127.0.0.1:8080/rpc.php").mock(side_effect=handler)
    backend = HttpBackend(settings(monkeypatch))
    assert await backend.call("System", "noop") is True
    assert calls == ["login", "noop", "login", "noop"]
    await backend.close()


@respx.mock
async def test_429_login_retries_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = body(request)
        calls.append(payload["method"])
        if payload["method"] == "login" and calls.count("login") == 1:
            return httpx.Response(429)
        if payload["method"] == "login":
            return httpx.Response(
                200, json={"response": {"status": "authenticated", "sessionid": "s"}}
            )
        return httpx.Response(200, json={"response": True})

    respx.post("http://127.0.0.1:8080/rpc.php").mock(side_effect=handler)
    backend = HttpBackend(settings(monkeypatch))
    assert await backend.call("System", "noop") is True
    assert calls.count("login") == 2
    await backend.close()


@respx.mock
async def test_error_object_has_no_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = body(request)
        if payload["method"] == "login":
            return httpx.Response(
                200, json={"response": {"status": "authenticated", "sessionid": "s"}}
            )
        return httpx.Response(
            200, json={"error": {"code": 42, "message": "bad thing", "trace": "SECRET TRACE"}}
        )

    respx.post("http://127.0.0.1:8080/rpc.php").mock(side_effect=handler)
    backend = HttpBackend(settings(monkeypatch))
    with pytest.raises(OmvRpcError) as exc:
        await backend.call("A", "b")
    assert exc.value.code == 42
    assert "SECRET TRACE" not in str(exc.value)
    await backend.close()


@respx.mock
async def test_non_object_success_body(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = body(request)
        if payload["method"] == "login":
            return httpx.Response(
                200, json={"response": {"status": "authenticated", "sessionid": "s"}}
            )
        return httpx.Response(200, text="<html>maintenance</html>")

    respx.post("http://127.0.0.1:8080/rpc.php").mock(side_effect=handler)
    backend = HttpBackend(settings(monkeypatch))
    with pytest.raises(OmvRpcError, match="non-JSON"):
        await backend.call("System", "noop")
    await backend.close()


@respx.mock
async def test_fetch_file(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = body(request)
        if payload["method"] == "login":
            return httpx.Response(
                200, json={"response": {"status": "authenticated", "sessionid": "s"}}
            )
        return httpx.Response(200, content=b"\x89PNG")

    respx.post("http://127.0.0.1:8080/rpc.php").mock(side_effect=handler)
    respx.post("http://127.0.0.1:8080/download.php").mock(side_effect=handler)
    backend = HttpBackend(settings(monkeypatch))
    assert await backend.fetch_file("Rrd", "getGraph", {"kind": "cpu"}) == b"\x89PNG"
    await backend.close()
