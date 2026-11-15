# omv-mcp

A safety-first [MCP](https://modelcontextprotocol.io) server for administering
[OpenMediaVault](https://www.openmediavault.org) 8 over SSH or HTTP.

- **Read-only by default.** The server starts in the `readonly` tier.
- **Plan before write.** Mutating tools return a diff and a single-use confirm token.
- **No implicit apply.** OMV config changes stay dirty until you call `config_apply`
  with an explicit module list.
- **Audited and redacted.** JSONL audit log, recursive secret redaction, protected
  users/groups, mutation rate limit.
- **Plugin-aware.** Mergerfs, SnapRAID, compose, WireGuard, writecache and omv-extras
  tools are registered only when the plugin is installed.
- **Tested against a real OMV VM.** Unit tests run offline; integration tests use a
  disposable OMV 8 VM in Docker with a hardcoded loopback guard.

## Requirements

- Python 3.12 or 3.13 and [uv](https://docs.astral.sh/uv/)
- OpenMediaVault 8.x (developed against 8.6.1)
- SSH backend: root SSH access and a pinned `known_hosts` entry
- HTTP backend: an OMV admin account without MFA enabled

The SSH backend is preferred: no OMV password is stored, and it does not hit MFA or
web-session expiry.

## Install

Run from a checkout:

```sh
git clone https://github.com/alex-rs/omv-mcp.git
cd omv-mcp
uv sync --extra dev
uv run omv-mcp --help
```

Or install the command from Git:

```sh
uv tool install git+https://github.com/alex-rs/omv-mcp
omv-mcp --help
```

This project is not on PyPI. The `omv-mcp` package on PyPI is unrelated; do not use
`uvx omv-mcp` or `pip install omv-mcp`.

## Configure

Configuration is environment variables or CLI flags; flags win. There is no config
file. For a real NAS, start read-only:

```sh
export OMV_MCP_MODE=readonly
export OMV_MCP_BACKEND=ssh
export OMV_MCP_SSH_HOST=nas.example.lan
export OMV_MCP_SSH_PORT=22
export OMV_MCP_SSH_USER=root          # v1 requires root
export OMV_MCP_SSH_KEY=~/.ssh/id_ed25519
export OMV_MCP_SSH_KNOWN_HOSTS=~/.ssh/known_hosts
```

The SSH backend validates the host key against OpenSSH's `known_hosts`; a missing or
untrusted entry fails closed. Add the NAS key with `ssh-keyscan` only after verifying
the fingerprint out of band.

Equivalent flags:

```sh
omv-mcp --backend ssh --host nas.example.lan --port 22 \
  --ssh-key ~/.ssh/id_ed25519 --ssh-known-hosts ~/.ssh/known_hosts \
  --mode readonly
```

### HTTP backend

Use HTTPS outside the disposable test VM; a plain `http://` URL sends the admin
password in clear text.

```sh
export OMV_MCP_BACKEND=http
export OMV_MCP_HTTP_URL=https://nas.example.lan
export OMV_MCP_HTTP_USERNAME=admin
export OMV_MCP_HTTP_PASSWORD=...
# export OMV_MCP_TLS_CA=/path/to/ca.pem   # optional private CA
```

If OMV returns `challengeRequired`, MFA is enabled for that account. Use a dedicated
non-MFA admin or the SSH backend.

### MCP client

Claude Code, using the installed command:

```sh
claude mcp add omv -- omv-mcp \
  --backend ssh --host nas.example.lan --mode readonly
```

Generic MCP client configuration:

```json
{
  "mcpServers": {
    "omv": {
      "command": "omv-mcp",
      "args": [
        "--backend", "ssh",
        "--host", "nas.example.lan",
        "--ssh-key", "~/.ssh/id_ed25519",
        "--ssh-known-hosts", "~/.ssh/known_hosts",
        "--mode", "readonly"
      ]
    }
  }
}
```

To serve MCP itself over HTTP, set `OMV_MCP_TRANSPORT=http` and
`OMV_MCP_HTTP_TOKEN` (required). The default bind is `127.0.0.1:8000`; non-loopback
binds without a token are refused. Put TLS in front of any remote deployment.

## Modes

| Mode | Adds |
|---|---|
| `readonly` (default) | All read tools, including read-only `rpc_call` |
| `operator` | Share/user/group/cron/rsync edits, SMART and SnapRAID jobs, writecache flush, config apply/revert |
| `admin` | Deletes, package/plugin installs, arbitrary non-read-only RPCs, and power (only with `OMV_MCP_ALLOW_POWER=true`) |

Dangerous methods (disk wipe, filesystem create/umount, network/firewall/SSH/WireGuard
writes, cterm, engine attach, and similar) are never exposed, even in `admin`.

## Safety model

OMV `set*` RPCs only update `config.xml` and mark modules dirty; nothing is live until
`Config.applyChanges`. This server makes that explicit:

1. Inspect with `config_pending` and the relevant read tools.
2. A write tool returns a plan: RPCs, before/after, side effects and dirty modules.
3. Re-call with `confirm_token`. The token is HMAC-signed, bound to the tool and
   canonical arguments, expires in 5 minutes and is single-use.
4. Execution re-checks the target and dirty-module set. `apply=true` is refused when
   unrelated modules were already dirty.
5. Call `config_apply` with the exact modules to deploy. It never applies everything.

Writes are audited to `~/.local/state/omv-mcp/audit.jsonl`, redacted, and rate-limited.
Shared folders referenced by SMB/NFS/rsync/compose cannot be deleted. Protected users
and groups are configurable via `OMV_MCP_PROTECT`.

See [SECURITY.md](SECURITY.md) for the threat model and exclusions.

## Settings

| Variable | Default | Notes |
|---|---|---|
| `OMV_MCP_MODE` | `readonly` | `readonly`, `operator`, `admin` |
| `OMV_MCP_BACKEND` | `ssh` | `ssh` or `http` |
| `OMV_MCP_TRANSPORT` | `stdio` | `stdio` or `http` |
| `OMV_MCP_SSH_HOST` | — | Required for SSH |
| `OMV_MCP_SSH_PORT` | `22` | |
| `OMV_MCP_SSH_USER` | `root` | Must be `root` in v1 |
| `OMV_MCP_SSH_KEY` | OpenSSH default | Path; `~` expanded |
| `OMV_MCP_SSH_KNOWN_HOSTS` | OpenSSH default | Usually `~/.ssh/known_hosts`; set explicitly for production |
| `OMV_MCP_RPC_USER` | `admin` | User passed to `omv-rpc -u` |
| `OMV_MCP_HTTP_URL` | — | Required for HTTP backend |
| `OMV_MCP_HTTP_USERNAME` | `admin` | |
| `OMV_MCP_HTTP_PASSWORD` | — | Required for HTTP backend |
| `OMV_MCP_TLS_VERIFY` | `true` | Do not disable against a real NAS |
| `OMV_MCP_TLS_CA` | — | Implies TLS verification |
| `OMV_MCP_HTTP_TOKEN` | — | Required for HTTP transport |
| `OMV_MCP_ALLOW_POWER` | `false` | Registers `system_power` |
| `OMV_MCP_AUDIT_PATH` | `~/.local/state/omv-mcp/audit.jsonl` | |
| `OMV_MCP_RATE_LIMIT_PER_MINUTE` | `10` | Confirmed writes |
| `OMV_MCP_RESPONSE_MAX_BYTES` | `25000` | Response cap |

## Tool surface

`docs/tools.md` contains the generated reference, including tiers, RPCs and side
effects. The read-only surface covers:

- system, CPU/top, time, services, logs, diagnostic report, RRD graphs
- disks, filesystems, fstab, SMART, quotas and a composite health summary
- shared folders, ACLs, snapshots, SMB/NFS/rsyncd shares
- users and groups
- cron, rsync and background jobs
- apt updates/changelogs, plugins
- network interfaces, firewall rules, certificates (public material only)
- mergerfs, SnapRAID, compose, WireGuard and writecache (when installed)

Operators and admins additionally get the plan/confirm write tools.

## Development

```sh
make check                          # ruff, mypy, unit tests, docs freshness
make smoke                          # read-only check against the test VM
OMV_MCP_TEST_VM=1 uv run pytest -m integration
```

The test VM is a real OMV 8 VM running under QEMU/KVM inside Docker:

```sh
make testenv-build                  # download Debian cloud image, create disks
make testenv-provision              # install OMV, plugins, seed state
make testenv-up                     # boot overlays from the seeded base
make testenv-reset                  # discard overlay writes
make testenv-destroy                # remove all VM state
```

`make testenv-*` and the integration suite only target `127.0.0.1:2222` and
`127.0.0.1:8080/8081/18080`, with hostname `omv-test`. This guard applies to the
bundled tests and scripts, not to a server you configure yourself.

## License

MIT. See [LICENSE](LICENSE).
