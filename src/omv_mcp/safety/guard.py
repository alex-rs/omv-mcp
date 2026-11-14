from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from omv_mcp.rpc.base import RpcBackend


class SafetyError(Exception):
    pass


NEVER_EXPOSED: frozenset[str] = frozenset(
    {
        "DiskMgmt.wipe",
        "FileSystemMgmt.create",
        "FileSystemMgmt.createBtrfs",
        "FileSystemMgmt.grow",
        "FileSystemMgmt.umountByDir",
        "FileSystemMgmt.umountByFsName",
        "FileSystemMgmt.setMountPoint",
        "FsTab.set",
        "FsTab.delete",
        "Network.setGeneralSettings",
        "Network.setBondIface",
        "Network.setBridgeIface",
        "Network.setEthernetIface",
        "Network.setVlanIface",
        "Network.setWirelessIface",
        "Network.setProxy",
        "Network.deleteInterface",
        "Iptables.setRule",
        "Iptables.setRules",
        "Iptables.setRules6",
        "SSH.set",
        "Wireguard.setTunnel",
        "Wireguard.setClient",
        "Wireguard.setCustom",
        "Wireguard.deleteTunnel",
        "Wireguard.deleteClient",
        "Wireguard.deleteCustom",
        "WebGui.setSettings",
        "UserMgmt.setSettings",
        "UserMgmt.setPasswordByContext",
        "CertificateMgmt.delete",
        "CertificateMgmt.deleteSsh",
        "CertificateMgmt.copySshId",
        "Compose.reinstallDocker",
        "Compose.doDownAll",
        "Compose.doDockerCmd",
        "Compose.doGit",
        "Compose.doHubPush",
        "Exec.attach",
        "Apt.upload",
        "Plugin.upload",
        "EnvVars.set",
        "EnvVars.apply",
        "EnvVars.applyBg",
    }
)

RO_METHOD_RE = re.compile(r"^(get|enumerate|is)[A-Z]|^getList$|^get$")
RO_DENY: frozenset[str] = frozenset(
    {
        "Session.login",
        "Session.verify",
        "Session.logout",
        "UserMgmt.authUser",
        "UserMgmt.verifyChallenge",
        "Exec.attach",
        "Wireguard.getTunnelConfig",
        "Wireguard.getClientConfig",
        "Wireguard.getCustom",
        "Wireguard.getCustomList",
        "CertificateMgmt.get",
        "CertificateMgmt.getDetail",
        "WebGui.getLocalStorageItems",
        "Compose.getFile",
    }
)


def is_never_exposed(service: str, method: str) -> bool:
    return (
        f"{service.casefold()}.{method.casefold()}" in {item.casefold() for item in NEVER_EXPOSED}
        or service.casefold() == "cterm"
    )


def is_ro_method(service: str, method: str) -> bool:
    name = f"{service.casefold()}.{method.casefold()}"
    if is_never_exposed(service, method) or name in {item.casefold() for item in RO_DENY}:
        return False
    if method.casefold().startswith("download"):
        return False
    return bool(RO_METHOD_RE.match(method))


def check_protected_user(name: str, protected: frozenset[str]) -> None:
    if name in protected:
        raise SafetyError(f"refusing to modify protected user {name}")


def check_protected_group(name: str, protected: frozenset[str]) -> None:
    if name in protected:
        raise SafetyError(f"refusing to modify protected group {name}")


def _contains_uuid(value: Any, uuid: str) -> bool:
    if isinstance(value, dict):
        return any(_contains_uuid(item, uuid) for item in value.values())
    if isinstance(value, list):
        return any(_contains_uuid(item, uuid) for item in value)
    return bool(value == uuid)


async def shared_folder_refs(backend: RpcBackend, uuid: str) -> list[str]:
    sources = [
        ("SMB", "SMB", "getShareList"),
        ("NFS", "NFS", "getShareList"),
        ("Rsync", "Rsync", "getList"),
        ("Rsyncd", "Rsyncd", "getModuleList"),
        ("Compose", "Compose", "get"),
    ]
    refs: list[str] = []
    for label, service, method in sources:
        params = None
        if method in {"getShareList", "getList", "getModuleList"}:
            params = {"start": 0, "limit": -1}
        result = await backend.call(service, method, params)
        if _contains_uuid(result, uuid):
            refs.append(label)
    return refs


class RateLimiter:
    def __init__(self, per_minute: int, now: Any = time.monotonic) -> None:
        self._limit = per_minute
        self._now = now
        self._events: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            current = self._now()
            self._events = [event for event in self._events if current - event < 60]
            if len(self._events) >= self._limit:
                raise SafetyError("rate limit exceeded; try again in a minute")
            self._events.append(current)
