from __future__ import annotations

from omv_mcp.server import build_server
from omv_mcp.settings import Mode, Settings


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


async def test_admin_server_includes_writes_and_power() -> None:
    settings = Settings(ssh_host="127.0.0.1", mode=Mode.ADMIN, allow_power=True)
    server = build_server(settings)
    names = {tool.name for tool in await server.list_tools()}
    assert "config_apply" in names
    assert "system_power" in names
    assert "user_delete" in names


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
