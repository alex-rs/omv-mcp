from __future__ import annotations

import asyncio
import secrets
from pathlib import Path
from typing import Any

import asyncssh

from omv_mcp.omv import NEW_UUID
from omv_mcp.rpc.jobs import JobRunner
from omv_mcp.rpc.ssh import SshBackend
from omv_mcp.settings import Backend, Settings
from testenv.guard import assert_test_target, assert_test_vm

BASE = Path("testenv/.state")
SERIALS = {
    "OMVTESTSSD1",
    "OMVTESTSSD2",
    "OMVTESTSSD3",
    "OMVTESTHDD1",
    "OMVTESTHDD2",
    "OMVTESTHDD3",
    "OMVTESTNVME1",
}


def rows(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, dict) and isinstance(result.get("data"), list):
        return [item for item in result["data"] if isinstance(item, dict)]
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    return []


class Seed:
    def __init__(self) -> None:
        self.settings = Settings(
            backend=Backend.SSH,
            ssh_host="127.0.0.1",
            ssh_port=2222,
            ssh_key=BASE / "id_ed25519",
            ssh_known_hosts=BASE / "known_hosts",
            rpc_user="admin",
        )
        self.backend = SshBackend(self.settings)
        self.jobs = JobRunner(self.backend, poll_interval=1.0, tail_bytes=8192)
        self.folders: dict[str, dict[str, Any]] = {}

    async def call(self, service: str, method: str, params: dict[str, Any] | None = None) -> Any:
        return await self.backend.call(service, method, params or {}, timeout=300)

    async def list(self, service: str, method: str, params: dict[str, Any] | None = None) -> Any:
        payload = dict(params or {})
        payload.setdefault("start", 0)
        payload.setdefault("limit", -1)
        return await self.call(service, method, payload)

    async def apply(self, modules: list[str]) -> None:
        if modules:
            await self.call(
                "Config", "applyChanges", {"modules": sorted(set(modules)), "force": False}
            )

    async def dirty(self) -> list[str]:
        info = await self.call("System", "getInformation")
        value = info.get("dirtyModules", []) if isinstance(info, dict) else []
        if isinstance(value, dict):
            return sorted(str(key) for key, item in value.items() if item)
        return sorted(str(item) for item in value)

    async def run_job(self, service: str, method: str, params: dict[str, Any]) -> Any:
        result = await self.call(service, method, params)
        if isinstance(result, str):
            job = await self.jobs.wait(result, 300)
            return job.model_dump()
        return result

    async def disks(self) -> None:
        listing = await self.list("DiskMgmt", "getList")
        by_serial = {
            str(item.get("serialnumber")): item
            for item in rows(listing)
            if item.get("serialnumber")
        }
        missing = SERIALS - set(by_serial)
        if missing:
            raise RuntimeError(f"missing test disks by serial: {sorted(missing)}")
        existing_fs = await self.filesystem_by_serial()
        for serial in SERIALS:
            disk = by_serial[serial]
            devicefile = str(disk.get("devicefile"))
            if serial in existing_fs:
                continue
            if not devicefile:
                raise RuntimeError(f"disk {serial} has no devicefile")
            print(f"creating ext4 on {devicefile} ({serial})")
            await self.run_job(
                "FileSystemMgmt", "create", {"devicefile": devicefile, "type": "ext4"}
            )
            await self.apply(["fstab"])

        detected = rows(await self.call("FileSystemMgmt", "enumerateFilesystems"))
        target_devices = {
            str(disk.get(key))
            for disk in by_serial.values()
            for key in ("devicefile", "canonicaldevicefile")
            if disk.get(key)
        }
        target_devices |= {
            f"/dev/{disk.get('devicename')}"
            for disk in by_serial.values()
            if disk.get("devicename")
        }
        for item in detected:
            parent = str(item.get("parentdevicefile") or "")
            device = str(item.get("devicefile") or "")
            if parent in target_devices or device in target_devices:
                fs_id = item.get("uuid") or item.get("predictabledevicefile")
                if not fs_id:
                    continue
                try:
                    await self.call("FileSystemMgmt", "setMountPoint", {"id": fs_id})
                except Exception as exc:
                    if "already exists" not in str(exc):
                        raise
        await self.apply(["fstab"])
        mounted = rows(await self.list("FileSystemMgmt", "getList"))
        for item in mounted:
            if item.get("devicefile") in {
                str(d.get("devicefile")) for d in by_serial.values()
            } and not item.get("mounted"):
                raise RuntimeError(f"filesystem {item.get('devicefile')} did not mount")

    async def filesystem_by_device(self) -> dict[str, dict[str, Any]]:
        return {
            str(item.get("devicefile")): item
            for item in rows(await self.list("FileSystemMgmt", "getList"))
        }

    async def filesystem_by_serial(self) -> dict[str, dict[str, Any]]:
        disks = rows(await self.list("DiskMgmt", "getList"))
        filesystems = rows(await self.list("FileSystemMgmt", "getList"))
        detected = rows(await self.call("FileSystemMgmt", "enumerateFilesystems"))
        parent_by_uuid = {
            str(item.get("uuid")): str(item.get("parentdevicefile") or "") for item in detected
        }
        by_parent = {
            str(item.get("parentdevicefile") or parent_by_uuid.get(str(item.get("uuid")))): item
            for item in filesystems
        }
        result: dict[str, dict[str, Any]] = {}
        for disk in disks:
            serial = str(disk.get("serialnumber") or "")
            if not serial:
                continue
            parent = str(disk.get("canonicaldevicefile") or f"/dev/{disk.get('devicename')}")
            row = by_parent.get(parent)
            if row:
                result[serial] = row
        return result

    async def device_by_serial(self) -> dict[str, str]:
        return {
            str(item.get("serialnumber")): str(item.get("devicefile"))
            for item in rows(await self.list("DiskMgmt", "getList"))
            if item.get("serialnumber")
        }

    async def pool(self) -> None:
        fs = await self.filesystem_by_serial()
        branches = [
            fs[serial]["mountpoint"] for serial in ("OMVTESTHDD1", "OMVTESTHDD2", "OMVTESTHDD3")
        ]
        pools = rows(await self.list("Mergerfs", "getList"))
        existing = next((item for item in pools if item.get("name") == "pool"), None)
        await self.call(
            "Mergerfs",
            "set",
            {
                "uuid": existing["uuid"] if existing else NEW_UUID,
                "name": "pool",
                "paths": ":".join(branches),
                "createpolicy": "ff",
                "options": "defaults,cache.files=off",
                "minfreespace": 1,
                "minfreespaceunit": "G",
            },
        )
        await self.apply(["mergerfs", "fstab"])
        await self.call("System", "noop")

    async def snapraid(self) -> None:
        fs = await self.filesystem_by_serial()
        arrays = rows(await self.list("SnapRaid", "getArrayList"))
        if not any(item.get("name") == "main" for item in arrays):
            await self.call(
                "SnapRaid",
                "setArray",
                {"uuid": NEW_UUID, "name": "main"},
            )
            arrays = rows(await self.list("SnapRaid", "getArrayList"))
        arrayref = arrays[0]["uuid"] if arrays else NEW_UUID
        existing_drives = {
            item.get("name") for item in rows(await self.list("SnapRaid", "getDriveList"))
        }
        for name, serial, content, data, parity in (
            ("data1", "OMVTESTHDD1", True, True, False),
            ("data2", "OMVTESTHDD2", True, True, False),
            ("parity1", "OMVTESTHDD3", False, False, True),
        ):
            if name in existing_drives:
                continue
            device = fs[serial]
            await self.call(
                "SnapRaid",
                "setDrive",
                {
                    "uuid": NEW_UUID,
                    "arrayref": arrayref,
                    "mntentref": device.get("mntentref") or device.get("uuid"),
                    "name": name,
                    "content": content,
                    "data": data,
                    "parity": parity,
                    "paritynum": 1,
                    "paritysplit": False,
                },
            )
        await self.apply(["snapraid"])

    async def shared_folders(self) -> None:
        fs = await self.filesystem_by_serial()
        pool = next(
            (item for item in fs.values() if item.get("type") == "fuse.mergerfs"),
            None,
        )
        if pool is None:
            listing = rows(await self.list("FileSystemMgmt", "getList"))
            pool = next((item for item in listing if item.get("type") == "fuse.mergerfs"), None)
        if pool is None:
            raise RuntimeError("mergerfs pool filesystem not found")
        targets = [
            ("compose-files", fs["OMVTESTSSD1"]),
            ("docker-data", fs["OMVTESTSSD1"]),
            ("compose-backup", fs["OMVTESTSSD2"]),
            ("downloads", fs["OMVTESTSSD3"]),
            ("music", fs["OMVTESTSSD3"]),
            ("recordings", fs["OMVTESTNVME1"]),
            ("pool-backup", pool),
            ("media", pool),
            ("archive", pool),
        ]
        existing = {
            item.get("name"): item for item in rows(await self.list("ShareMgmt", "getList"))
        }
        mntents = rows(await self.list("FsTab", "enumerateEntries"))
        by_fsname = {str(item.get("fsname")): str(item.get("uuid")) for item in mntents}
        await self.call("ShareMgmt", "getCandidates")
        for name, filesystem in targets:
            mntentref = by_fsname.get(str(filesystem.get("devicefile"))) or by_fsname.get(
                str(filesystem.get("uuid"))
            )
            if not mntentref:
                raise RuntimeError(f"no mount entry for shared folder {name}")
            folder = existing.get(name)
            params = {
                "uuid": folder.get("uuid") if folder and folder.get("uuid") else NEW_UUID,
                "name": name,
                "reldirpath": name,
                "comment": "",
                "mntentref": mntentref,
            }
            await self.call("ShareMgmt", "set", params)
            if not folder:
                folder = {"name": name, "uuid": None}
            self.folders[name] = folder
        await self.apply(["shares"])

        for name, folder in self.folders.items():
            if not folder.get("uuid"):
                listing = rows(await self.list("ShareMgmt", "getList"))
                folder = next((item for item in listing if item.get("name") == name), {})
                self.folders[name] = folder
        compose_folder = self.folders["compose-files"]
        path = await self.call("ShareMgmt", "getPath", {"uuid": compose_folder["uuid"]})
        conn = await asyncssh.connect(
            "127.0.0.1",
            port=2222,
            username="root",
            client_keys=[str(self.settings.ssh_key)],
            known_hosts=str(self.settings.ssh_known_hosts),
        )
        try:
            await conn.run(f"mkdir -p {path}/whoami")
            compose = (
                "services:\n  whoami:\n    image: traefik/whoami\n    ports:\n      - '9000:80'\n"
            )
            await conn.run(f"cat > {path}/whoami/compose.yaml", input=compose)
        finally:
            conn.close()

    async def compose(self) -> None:
        current = await self.call("Compose", "get")
        if not isinstance(current, dict):
            raise RuntimeError("Compose.get did not return settings")
        allowed = {
            "sharedfolderref",
            "composeowner",
            "composegroup",
            "mode",
            "datasharedfolderref",
            "backupsharedfolderref",
            "backupmaxsize",
            "backupbackend",
            "borgkeep",
            "borgencryption",
            "borgpassphrase",
            "dockersharedfolderref",
            "logmaxsize",
            "liverestore",
            "createsymlinks",
            "podmansharedfolderref",
            "urlHostname",
            "cachetimefiles",
            "cachetimeservices",
            "cachetimestats",
            "cachetimeimages",
            "cachetimenetworks",
            "cachetimevolumes",
            "cachetimecontainers",
            "showcmd",
            "podman",
            "runconfig",
        }
        settings = {key: value for key, value in current.items() if key in allowed}
        settings["sharedfolderref"] = self.folders["compose-files"]["uuid"]
        settings["datasharedfolderref"] = self.folders["docker-data"]["uuid"]
        settings["backupsharedfolderref"] = self.folders["compose-backup"]["uuid"]
        await self.call("Compose", "set", settings)
        await self.apply(["compose"])
        conn = await asyncssh.connect(
            "127.0.0.1",
            port=2222,
            username="root",
            client_keys=[str(self.settings.ssh_key)],
            known_hosts=str(self.settings.ssh_known_hosts),
        )
        try:
            await conn.run("systemctl enable --now docker")
        finally:
            conn.close()

    async def writecache(self) -> None:
        await self.call(
            "WriteCache",
            "setSettings",
            {
                "enable": True,
                "use_tmpfs": True,
                "sharedfolderref": "",
                "tmpfs_size": "25%",
                "ram_backing": "tmpfs",
                "zram_size": "512M",
                "zram_algo": "zstd",
                "journald_storage": "volatile",
                "flush_on_boot": False,
                "flush_on_shutdown": True,
                "rotate_on_shutdown": True,
                "flush_hourly": False,
                "flush_daily": True,
                "hour": 3,
                "minute": 45,
                "rotate_on_daily_flush": True,
                "paths": "",
                "services": "",
            },
        )
        await self.apply(["writecache"])

    async def smart(self) -> None:
        await self.call(
            "Smart",
            "setSettings",
            {
                "enable": True,
                "interval": 10,
                "powermode": "standby",
                "tempdiff": 2,
                "tempmax": 60,
            },
        )
        devices = {
            str(item.get("devicefile")): item for item in rows(await self.list("Smart", "getList"))
        }
        for devicefile, kind in (("/dev/sdb", "S"), ("/dev/sdd", "L")):
            device = devices.get(devicefile)
            if device:
                await self.call(
                    "Smart",
                    "setScheduledTest",
                    {
                        "uuid": NEW_UUID,
                        "enable": True,
                        "devicefile": devicefile,
                        "comment": f"{kind} test",
                        "type": kind,
                        "hour": "03",
                        "month": "*",
                        "dayofmonth": "*",
                        "dayofweek": "1",
                    },
                )
        await self.apply(["smartmontools"])

    async def power(self) -> None:
        await self.call(
            "PowerMgmt", "set", {"cpufreqgovernor": "powersave", "powerbtn": "shutdown"}
        )
        await self.apply(["powermgmt"])

    async def users(self) -> None:
        existing = {item.get("name") for item in rows(await self.list("UserMgmt", "getUserList"))}
        if "tester" not in existing:
            await self.call(
                "UserMgmt",
                "setUser",
                {
                    "name": "tester",
                    "groups": ["users"],
                    "shell": "/usr/sbin/nologin",
                    "password": "",
                    "email": "",
                    "comment": "test user",
                    "disallowusermod": False,
                    "sshpubkeys": [],
                },
            )
        password = (BASE / "mfa-user.pass").read_text().strip()
        if "mfatester" not in existing:
            await self.call(
                "UserMgmt",
                "setUser",
                {
                    "name": "mfatester",
                    "groups": ["users"],
                    "shell": "/bin/bash",
                    "password": password,
                    "email": "",
                    "comment": "MFA test user",
                    "disallowusermod": False,
                    "sshpubkeys": [],
                },
            )
        await self.apply(["user"])
        try:
            items = await self.list("TfaTotp", "getItemList")
            for item in rows(items):
                if item.get("name") == "mfatester":
                    await self.call("TfaTotp", "deleteItem", {"uuid": item.get("uuid")})
            await self.call(
                "TfaTotp",
                "setItem",
                {
                    "uuid": NEW_UUID,
                    "name": "mfatester",
                    "enabled": True,
                    "secret": secrets.token_hex(20),
                },
            )
            await self.apply(["tfatotp"])
        except Exception as exc:
            print(f"warning: TfaTotp setup failed: {exc}")

    async def leave_ssh_dirty(self) -> None:
        current = await self.call("SSH", "get")
        if not isinstance(current, dict):
            raise RuntimeError("SSH.get did not return settings")
        current.update(
            {
                "enable": True,
                "permitrootlogin": True,
                "pubkeyauthentication": True,
                "passwordauthentication": True,
            }
        )
        await self.call("SSH", "set", current)

    async def finish(self) -> None:
        for _ in range(5):
            current = await self.dirty()
            if current == ["ssh"]:
                break
            await self.apply([module for module in current if module != "ssh"])
        remaining = await self.dirty()
        if remaining != ["ssh"]:
            raise RuntimeError(f"expected only ssh dirty, got {remaining}")
        await self.call("System", "shutdown", {"delay": 0})
        await asyncio.sleep(2)
        (BASE / "base" / "PROVISIONED").touch()
        for disk in (BASE / "base").glob("*.qcow2"):
            disk.chmod(0o444)


async def main() -> None:
    seed = Seed()
    assert_test_target(seed.settings)
    try:
        await assert_test_vm(seed.backend)
        await seed.disks()
        await seed.pool()
        await seed.snapraid()
        await seed.shared_folders()
        await seed.compose()
        await seed.writecache()
        await seed.smart()
        await seed.power()
        await seed.users()
        await seed.leave_ssh_dirty()
        await seed.finish()
        print("seed complete")
    finally:
        await seed.backend.close()


if __name__ == "__main__":
    asyncio.run(main())
