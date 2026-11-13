from __future__ import annotations

import json
import shlex
from typing import Any

import asyncssh
import pytest

from omv_mcp.rpc.errors import OmvRpcError
from omv_mcp.rpc.ssh import SshBackend, build_command
from omv_mcp.settings import Settings


class Result:
    def __init__(self, stdout: Any = b"", stderr: Any = b"", exit_status: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.exit_status = exit_status


class Conn:
    def __init__(self, results: list[Any]) -> None:
        self.results = results
        self.commands: list[str] = []
        self.closed = False

    async def run(
        self,
        command: str,
        *,
        check: bool = False,
        timeout: float | None = None,
        encoding: str | None = None,
    ) -> Result:
        self.commands.append(command)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result  # type: ignore[no-any-return]

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("OMV_MCP_SSH_HOST", "127.0.0.1")
    monkeypatch.setenv("OMV_MCP_SSH_PORT", "2222")
    return Settings()


async def test_build_command_quotes_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    params = {"x": "'\"$(id)`whoami`\n"}
    cmd = build_command("admin", "System", "noop", params)
    argv = shlex.split(cmd)
    assert argv[:5] == ["/usr/sbin/omv-rpc", "-u", "admin", "System", "noop"]
    assert json.loads(argv[5]) == params


async def test_stdout_response_and_session_header(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = Conn([Result(b'garbage\n{"response":{"hostname":"omv-test"}}\n')])

    async def connect(**kwargs: Any) -> Conn:
        return conn

    monkeypatch.setattr(asyncssh, "connect", connect)
    backend = SshBackend(settings(monkeypatch))
    assert await backend.call("System", "getInformation") == {"hostname": "omv-test"}
    assert conn.commands


async def test_error_json_on_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = Conn([Result(b"", b'{"error":{"code":7,"message":"nope","trace":"secret"}}\n', 1)])

    async def connect(**kwargs: Any) -> Conn:
        return conn

    monkeypatch.setattr(asyncssh, "connect", connect)
    backend = SshBackend(settings(monkeypatch))
    with pytest.raises(OmvRpcError) as exc:
        await backend.call("Test", "fail")
    assert exc.value.code == 7
    assert exc.value.message == "nope"
    assert "secret" not in str(exc.value)
    assert "Test.fail" in str(exc.value)


async def test_error_json_on_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = Conn([Result(b'{"error":{"code":500,"message":"bad"}}\n')])

    async def connect(**kwargs: Any) -> Conn:
        return conn

    monkeypatch.setattr(asyncssh, "connect", connect)
    with pytest.raises(OmvRpcError, match="bad"):
        await SshBackend(settings(monkeypatch)).call("A", "b")


async def test_non_json_and_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = Conn(
        [
            Result(b"", b"permission denied\n", 255),
            Result(b""),
            Result(b"", b"boom\n", 2),
        ]
    )

    async def connect(**kwargs: Any) -> Conn:
        return conn

    monkeypatch.setattr(asyncssh, "connect", connect)
    backend = SshBackend(settings(monkeypatch))
    with pytest.raises(OmvRpcError, match="permission denied"):
        await backend.call("A", "b")
    assert await backend.call("A", "b") is None
    with pytest.raises(OmvRpcError, match="boom"):
        await backend.call("A", "b")


async def test_reconnect_once(monkeypatch: pytest.MonkeyPatch) -> None:
    first = Conn([OSError("closed")])
    second = Conn([Result(b'{"response":true}\n')])
    created: list[Conn] = [first, second]

    async def connect(**kwargs: Any) -> Conn:
        return created.pop(0)

    monkeypatch.setattr(asyncssh, "connect", connect)
    backend = SshBackend(settings(monkeypatch))
    assert await backend.call("System", "noop") is True
    assert first.closed
    assert created == []


async def test_fetch_file_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = {
        "LogFile.getContent": {"filepath": "/tmp/omv-log.txt", "unlink": True},
        "Rrd.getGraph": {"filepath": "/var/lib/openmediavault/rrd/cpu.png"},
    }
    commands: list[str] = []

    async def fake_connect(**kwargs: Any) -> Any:
        class C:
            async def run(self, command: str, **kw: Any) -> Result:
                commands.append(command)
                if command.startswith("cat "):
                    return Result(b"log line\n")
                if command.startswith("rm -f "):
                    return Result()
                return Result(json.dumps({"response": responses[command_key(command)]}).encode())

            def close(self) -> None: ...
            async def wait_closed(self) -> None: ...

        return C()

    def command_key(command: str) -> str:
        service, method = shlex.split(command)[3:5]
        return f"{service}.{method}"

    monkeypatch.setattr(asyncssh, "connect", fake_connect)
    backend = SshBackend(settings(monkeypatch))
    assert await backend.fetch_file("LogFile", "getContent", {"id": "syslog"}) == b"log line\n"
    assert any(c.startswith("rm -f ") for c in commands)
    assert await backend.fetch_file("Rrd", "getGraph", {"kind": "cpu"}) == b"log line\n"


@pytest.mark.parametrize(
    "service,filepath", [("Other", "/tmp/x"), ("LogFile", "/etc/shadow"), ("Rrd", "/tmp/x.txt")]
)
async def test_fetch_file_rejects(
    monkeypatch: pytest.MonkeyPatch, service: str, filepath: str
) -> None:
    async def fake_connect(**kwargs: Any) -> Any:
        class C:
            async def run(self, command: str, **kw: Any) -> Result:
                return Result(json.dumps({"response": {"filepath": filepath}}).encode())

            def close(self) -> None: ...
            async def wait_closed(self) -> None: ...

        return C()

    monkeypatch.setattr(asyncssh, "connect", fake_connect)
    with pytest.raises(OmvRpcError, match=r"unsafe|allows|not allowed"):
        await SshBackend(settings(monkeypatch)).fetch_file(service, "x")
