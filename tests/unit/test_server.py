from __future__ import annotations

import pytest
from mcp.types import ToolAnnotations

from omv_mcp.server import build_server, probe_plugins
from omv_mcp.settings import Mode, Settings
from tests.unit.fakes import FakeBackend


async def test_readonly_server_has_only_readonly_tools() -> None:
    settings = Settings(ssh_host="127.0.0.1", mode=Mode.READONLY)
    server = build_server(settings)
    tools = await server.list_tools()
    assert tools
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools)
    names = {tool.name for tool in tools}
    assert "system_power" not in names
    assert "config_apply" not in names
    assert "rpc_call" in names
    assert "disk_wipe" not in names


async def test_rpc_call_annotation_matches_mode() -> None:
    async def rpc_annotations(mode: Mode) -> ToolAnnotations:
        server = build_server(Settings(ssh_host="127.0.0.1", mode=mode))
        tools = {tool.name: tool for tool in await server.list_tools()}
        annotations = tools["rpc_call"].annotations
        assert annotations is not None
        return annotations

    assert (await rpc_annotations(Mode.READONLY)).read_only_hint is True
    assert (await rpc_annotations(Mode.OPERATOR)).read_only_hint is True

    admin = await rpc_annotations(Mode.ADMIN)
    assert admin.read_only_hint is False
    assert admin.destructive_hint is True


async def test_admin_server_includes_writes_and_power() -> None:
    settings = Settings(ssh_host="127.0.0.1", mode=Mode.ADMIN, allow_power=True)
    server = build_server(settings)
    names = {tool.name for tool in await server.list_tools()}
    assert "config_apply" in names
    assert "system_power" in names
    assert "user_delete" in names


async def test_probe_plugins_ignores_available_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = FakeBackend(
        {
            ("Plugin", "getList"): {
                "total": 3,
                "data": [
                    {"name": "openmediavault-mergerfs", "installed": True},
                    {"name": "openmediavault-snapraid", "installed": False},
                    {"name": "openmediavault-writecache"},
                ],
            }
        }
    )
    monkeypatch.setattr("omv_mcp.server.make_backend", lambda _settings: backend)
    detected = await probe_plugins(Settings(ssh_host="127.0.0.1"))
    assert detected == frozenset({"openmediavault-mergerfs"})
    assert backend.closed


async def test_plugin_tools_only_when_installed() -> None:
    settings = Settings(ssh_host="127.0.0.1", mode=Mode.ADMIN)
    without = {tool.name for tool in await build_server(settings).list_tools()}
    assert "mergerfs_pools" not in without
    with_plugin = {
        tool.name
        for tool in await build_server(
            settings, plugins=frozenset({"openmediavault-mergerfs"})
        ).list_tools()
    }
    assert "mergerfs_pools" in with_plugin
