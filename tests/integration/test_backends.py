from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from omv_mcp.rpc.errors import OmvRpcError
from omv_mcp.rpc.http import HttpBackend
from omv_mcp.rpc.ssh import SshBackend
from omv_mcp.settings import Backend, Settings
from testenv.guard import assert_test_target, assert_test_vm

pytestmark = pytest.mark.integration
STATE = Path("testenv/.state")


async def test_ssh_system_information() -> None:
    settings = Settings(
        backend=Backend.SSH,
        ssh_host="127.0.0.1",
        ssh_port=2222,
        ssh_key=STATE / "id_ed25519",
        ssh_known_hosts=STATE / "known_hosts",
    )
    assert_test_target(settings)
    backend = SshBackend(settings)
    try:
        await assert_test_vm(backend)
        info = await backend.call("System", "getInformation")
        assert info["hostname"] == "omv-test"
        assert str(info["version"]).startswith("8.")
    finally:
        await backend.close()


async def test_http_login_relogin_and_mfa() -> None:
    password = (STATE / "omv-admin.pass").read_text().strip()
    settings = Settings(
        backend=Backend.HTTP,
        http_url="http://127.0.0.1:18080",
        http_password=SecretStr(password),
    )
    assert_test_target(settings)
    backend = HttpBackend(settings)
    try:
        await assert_test_vm(backend)
        await backend.call("Session", "logout")
        info = await backend.call("System", "getInformation")
        assert info["hostname"] == "omv-test"
    finally:
        await backend.close()

    mfa_password = (STATE / "mfa-user.pass").read_text().strip()
    mfa = HttpBackend(
        Settings(
            backend=Backend.HTTP,
            http_url="http://127.0.0.1:18080",
            http_username="mfatester",
            http_password=SecretStr(mfa_password),
        )
    )
    try:
        with pytest.raises(OmvRpcError, match="MFA is enabled for mfatester"):
            await mfa.call("System", "noop")
    finally:
        await mfa.close()
