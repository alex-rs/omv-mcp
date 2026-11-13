from __future__ import annotations

import pytest
from pydantic import ValidationError

from omv_mcp.settings import Backend, Mode, Settings, Transport


def test_defaults_readonly_ssh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMV_MCP_SSH_HOST", "127.0.0.1")
    s = Settings()
    assert s.mode is Mode.READONLY
    assert s.backend is Backend.SSH
    assert s.transport is Transport.STDIO
    assert s.mode_tier == 0


def test_ssh_host_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OMV_MCP_SSH_HOST", raising=False)
    with pytest.raises(ValidationError, match="OMV_MCP_SSH_HOST"):
        Settings()


def test_http_requires_url_and_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMV_MCP_BACKEND", "http")
    with pytest.raises(ValidationError, match="OMV_MCP_HTTP_URL"):
        Settings()
    monkeypatch.setenv("OMV_MCP_HTTP_URL", "http://127.0.0.1:8080")
    with pytest.raises(ValidationError, match="OMV_MCP_HTTP_PASSWORD"):
        Settings()


def test_http_transport_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMV_MCP_SSH_HOST", "127.0.0.1")
    monkeypatch.setenv("OMV_MCP_TRANSPORT", "http")
    with pytest.raises(ValidationError, match="OMV_MCP_HTTP_TOKEN"):
        Settings()


def test_root_ssh_user_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMV_MCP_SSH_HOST", "127.0.0.1")
    monkeypatch.setenv("OMV_MCP_SSH_USER", "admin")
    with pytest.raises(ValidationError, match="requires SSH user root"):
        Settings()


def test_protected_sets_and_expanduser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMV_MCP_SSH_HOST", "127.0.0.1")
    monkeypatch.setenv("OMV_MCP_PROTECT", "user:root, group:sudo,user:tester")
    s = Settings()
    assert s.protected_users == frozenset({"root", "tester"})
    assert s.protected_groups == frozenset({"sudo"})


def test_tls_ca_implies_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMV_MCP_SSH_HOST", "127.0.0.1")
    monkeypatch.setenv("OMV_MCP_TLS_VERIFY", "false")
    monkeypatch.setenv("OMV_MCP_TLS_CA", "~/ca.pem")
    s = Settings()
    assert s.tls_verify is True
    assert str(s.tls_ca).startswith("/")


def test_cli_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMV_MCP_SSH_HOST", "127.0.0.1")
    monkeypatch.setenv("OMV_MCP_MODE", "readonly")
    s = Settings(mode=Mode.ADMIN, ssh_port=2222)
    assert s.mode is Mode.ADMIN
    assert s.ssh_port == 2222
