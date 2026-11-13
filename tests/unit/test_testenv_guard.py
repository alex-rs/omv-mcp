from __future__ import annotations

import pytest
from pydantic import SecretStr

from omv_mcp.settings import Backend, Settings
from testenv.guard import assert_test_target


def test_rejects_non_test_ssh_port() -> None:
    settings = Settings(ssh_host="127.0.0.1", ssh_port=2223)
    with pytest.raises(RuntimeError, match=r"127\.0\.0\.1:2222"):
        assert_test_target(settings)


def test_rejects_non_loopback_http() -> None:
    settings = Settings(
        backend=Backend.HTTP,
        http_url="http://192.0.2.10:18080",
        http_password=SecretStr("x"),
    )
    with pytest.raises(RuntimeError, match="local OMV test VM"):
        assert_test_target(settings)
