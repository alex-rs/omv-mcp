from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import asyncssh

from omv_mcp.settings import Backend, Settings
from testenv.guard import assert_test_target, assert_test_vm


async def main() -> None:
    settings = Settings(
        backend=Backend.SSH,
        ssh_host="127.0.0.1",
        ssh_port=2222,
        ssh_key=Path("testenv/.state/id_ed25519"),
        ssh_known_hosts=Path("testenv/.state/known_hosts"),
        rpc_user="admin",
    )
    assert_test_target(settings)

    from omv_mcp.rpc.ssh import SshBackend

    backend = SshBackend(settings)
    try:
        await assert_test_vm(backend)
        schemas = Path("src/omv_mcp/schemas")
        schemas.mkdir(exist_ok=True)
        result = await backend.call("System", "getInformation")
        version = str(result.get("version", "unknown"))  # type: ignore[union-attr]
        conn = await asyncssh.connect(
            "127.0.0.1",
            port=2222,
            username="root",
            client_keys=[str(settings.ssh_key)],
            known_hosts=str(settings.ssh_known_hosts),
        )
        try:
            listing = await conn.run(
                "for f in /usr/share/openmediavault/datamodels/rpc.*.json; do "
                "printf '%s\\n' \"$f\"; done"
            )
            files = [line for line in str(listing.stdout).splitlines() if line.strip()]
            for remote in files:
                data = await conn.run(f"cat {remote}")
                (schemas / Path(remote).name).write_text(str(data.stdout))

            incs = await conn.run(
                'grep -H -o \'registerMethod("[^"]*"\' '
                "/usr/share/openmediavault/engined/rpc/*.inc || true"
            )
            services: dict[str, list[str]] = {}
            for line in str(incs.stdout).splitlines():
                path, _, method = line.partition(":")
                match = re.search(r'registerMethod\("([^"]+)"', method)
                if match:
                    service = Path(path).stem
                    services.setdefault(service, []).append(match.group(1))

            catalog_path = Path("plan/omv8-rpc-catalog.md")
            if catalog_path.exists():
                for row in catalog_path.read_text().splitlines():
                    parts = [part.strip() for part in row.strip("|").split("|")]
                    if len(parts) >= 3 and parts[0] != "Service":
                        names = parts[2].split()
                        if names:
                            services.setdefault(parts[0], [])
                            for name in names:
                                if name not in services[parts[0]]:
                                    services[parts[0]].append(name)

            catalog = {
                "source": f"openmediavault {version} test VM",
                "services": {k: sorted(set(v)) for k, v in sorted(services.items())},
            }
            (schemas / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n")
            print(f"captured {len(files)} schemas from OMV {version}")
        finally:
            conn.close()
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
