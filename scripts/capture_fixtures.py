from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from omv_mcp.rpc.redact import redact
from omv_mcp.rpc.ssh import SshBackend
from omv_mcp.settings import Backend, Settings
from testenv.guard import assert_test_target, assert_test_vm

STATE = Path("testenv/.state")
FIXTURES: list[tuple[str, str, dict[str, Any]]] = [
    ("System", "getInformation", {}),
    ("System", "getTimeSettings", {}),
    ("System", "getCpuStats", {}),
    ("System", "getCpuGovernors", {}),
    ("System", "getTopInfo", {"format": "json"}),
    ("Config", "isDirty", {}),
    ("DiskMgmt", "getList", {"start": 0, "limit": -1}),
    ("FileSystemMgmt", "getList", {"start": 0, "limit": -1}),
    ("FileSystemMgmt", "enumerateMountedFilesystems", {}),
    ("FsTab", "enumerateEntries", {"start": 0, "limit": -1}),
    ("Smart", "getList", {"start": 0, "limit": -1}),
    ("Smart", "getSettings", {}),
    ("Smart", "getScheduleList", {"start": 0, "limit": -1}),
    ("ShareMgmt", "getList", {"start": 0, "limit": -1}),
    ("ShareMgmt", "getCandidates", {}),
    ("SMB", "getSettings", {}),
    ("SMB", "getShareList", {"start": 0, "limit": -1}),
    ("NFS", "getSettings", {}),
    ("NFS", "getShareList", {"start": 0, "limit": -1}),
    ("Rsyncd", "getSettings", {}),
    ("Rsyncd", "getModuleList", {"start": 0, "limit": -1}),
    ("Rsync", "getList", {"start": 0, "limit": -1}),
    ("SSH", "get", {}),
    ("UserMgmt", "getUserList", {"start": 0, "limit": -1}),
    ("UserMgmt", "getGroupList", {"start": 0, "limit": -1}),
    ("Cron", "getList", {"start": 0, "limit": -1, "type": ["userdefined"]}),
    ("Exec", "enumerate", {}),
    ("Apt", "enumerateUpgraded", {"start": 0, "limit": -1}),
    ("Plugin", "getList", {"start": 0, "limit": -1}),
    ("Services", "getStatus", {}),
    ("PowerMgmt", "getScheduleList", {"start": 0, "limit": -1, "type": ["reboot"]}),
    ("Network", "getGeneralSettings", {}),
    ("Network", "getInterfaceList", {"start": 0, "limit": -1}),
    ("CertificateMgmt", "getList", {"start": 0, "limit": -1}),
    ("CertificateMgmt", "getSshList", {"start": 0, "limit": -1}),
    ("Iptables", "getRules", {}),
    ("Iptables", "getRules6", {}),
    ("Mergerfs", "getList", {"start": 0, "limit": -1}),
    ("SnapRaid", "getArrayList", {"start": 0, "limit": -1}),
    ("SnapRaid", "getDriveList", {"start": 0, "limit": -1}),
    ("WriteCache", "getSettings", {}),
    ("Compose", "get", {}),
    ("Compose", "getFileList", {"start": 0, "limit": -1}),
    ("Wireguard", "getTunnelList", {"start": 0, "limit": -1}),
    ("omvextras", "get", {}),
]


async def main() -> None:
    settings = Settings(
        backend=Backend.SSH,
        ssh_host="127.0.0.1",
        ssh_port=2222,
        ssh_key=STATE / "id_ed25519",
        ssh_known_hosts=STATE / "known_hosts",
    )
    assert_test_target(settings)
    backend = SshBackend(settings)
    out = Path("tests/fixtures")
    out.mkdir(parents=True, exist_ok=True)
    try:
        await assert_test_vm(backend)
        for service, method, params in FIXTURES:
            try:
                result = await backend.call(service, method, params)
            except Exception as exc:
                print(f"skip {service}.{method}: {exc}")
                continue
            path = out / f"{service}.{method}.json"
            path.write_text(json.dumps(redact(result), indent=2, default=str) + "\n")
            path.chmod(0o600)
        print(f"captured {len(list(out.glob('*.json')))} fixtures")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
