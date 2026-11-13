from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from mcp.types import ToolAnnotations


class Tier(IntEnum):
    READONLY = 0
    OPERATOR = 1
    ADMIN = 2


@dataclass(frozen=True)
class ToolSpec:
    name: str
    tier: Tier
    fn: Callable[..., Awaitable[Any]]
    description: str
    rpcs: tuple[str, ...]
    annotations: ToolAnnotations


def make_annotations(
    tier: Tier, *, destructive: bool = False, idempotent: bool = True
) -> ToolAnnotations:
    return ToolAnnotations(
        read_only_hint=tier is Tier.READONLY,
        destructive_hint=destructive,
        idempotent_hint=None if tier is not Tier.READONLY and not idempotent else idempotent,
        open_world_hint=True,
    )


def ro(name: str, fn: Callable[..., Awaitable[Any]], description: str, *rpcs: str) -> ToolSpec:
    return ToolSpec(name, Tier.READONLY, fn, description, rpcs, make_annotations(Tier.READONLY))


def op(
    name: str,
    fn: Callable[..., Awaitable[Any]],
    description: str,
    *rpcs: str,
    idempotent: bool = True,
) -> ToolSpec:
    return ToolSpec(
        name,
        Tier.OPERATOR,
        fn,
        description,
        rpcs,
        make_annotations(Tier.OPERATOR, idempotent=idempotent),
    )


def admin(
    name: str,
    fn: Callable[..., Awaitable[Any]],
    description: str,
    *rpcs: str,
    destructive: bool = False,
    idempotent: bool = True,
) -> ToolSpec:
    return ToolSpec(
        name,
        Tier.ADMIN,
        fn,
        description,
        rpcs,
        make_annotations(Tier.ADMIN, destructive=destructive, idempotent=idempotent),
    )


ALL_PLUGIN_PACKAGES: dict[str, str] = {
    "mergerfs": "openmediavault-mergerfs",
    "snapraid": "openmediavault-snapraid",
    "writecache": "openmediavault-writecache",
    "compose": "openmediavault-compose",
    "wireguard": "openmediavault-wireguard",
    "omvextras": "openmediavault-omvextrasorg",
}

_CORE_MODULES = (
    "omv_mcp.tools.core",
    "omv_mcp.tools.storage",
    "omv_mcp.tools.shares",
    "omv_mcp.tools.jobs_apt",
    "omv_mcp.tools.network",
)


def iter_tools(plugins: frozenset[str]) -> list[ToolSpec]:
    import importlib

    modules = list(_CORE_MODULES)
    for plugin, package in ALL_PLUGIN_PACKAGES.items():
        if package in plugins:
            modules.append(f"omv_mcp.tools.plugins.{plugin}")
    specs: list[ToolSpec] = []
    for module_name in modules:
        module = importlib.import_module(module_name)
        specs.extend(module.TOOLS)
    return specs
