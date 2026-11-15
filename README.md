# omv-mcp

An MCP server for administering OpenMediaVault 8 safely over SSH or HTTP.

- **Read-only by default.** Read tools never change OMV state.
- **Every write is a plan.** Re-call the tool with the returned confirm token to execute.
- **Never applies modules it did not dirty.** `config_apply` requires an explicit module list.
- **Audited and redacted.** JSONL audit records, secret redaction, protected users/groups.
- **Test-only target.** Development and integration tests use a disposable OMV 8 VM in Docker; never a production NAS.

## Install

```sh
uv sync
uv run omv-mcp --help
```

Or install this checkout as a tool:

```sh
uv tool install .
omv-mcp --backend ssh --host 127.0.0.1 --port 2222 --mode readonly
```

This project is not published on PyPI. The `omv-mcp` distribution on PyPI is an
unrelated project, so do not run `uvx omv-mcp` or `pip install omv-mcp`.

## Claude Code / MCP client

```sh
claude mcp add omv -- uv run --directory /path/to/omv-mcp omv-mcp \
  --backend ssh --host 127.0.0.1 --port 2222 --mode readonly
```

Replace `/path/to/omv-mcp` with this checkout; `uvx --from /path/to/omv-mcp omv-mcp`
works too. `127.0.0.1:2222` is the local disposable test VM. Point it at a real OMV
host only when you have deliberately chosen to do so; the test guard applies to the
bundled integration suite, not to a user-configured server.

## Modes

| Mode | Tools exposed |
|---|---|
| `readonly` (default) | read-only tools plus read-only `rpc_call` |
| `operator` | operator writes: shares, users, jobs, plugins updates |
| `admin` | admin writes: deletes, power (if enabled), arbitrary non-RO RPCs |

`system_power` is registered only with `OMV_MCP_ALLOW_POWER=true` and admin mode.

## Required settings

```sh
# SSH (preferred)
export OMV_MCP_BACKEND=ssh
export OMV_MCP_SSH_HOST=127.0.0.1
export OMV_MCP_SSH_PORT=2222
export OMV_MCP_SSH_USER=root          # v1 requires root
export OMV_MCP_SSH_KEY=~/.ssh/id_ed25519
export OMV_MCP_SSH_KNOWN_HOSTS=~/.ssh/known_hosts

# HTTP alternative (bearer token is required for the HTTP transport)
export OMV_MCP_BACKEND=http
export OMV_MCP_HTTP_URL=http://127.0.0.1:18080
export OMV_MCP_HTTP_PASSWORD=...
export OMV_MCP_TRANSPORT=http
export OMV_MCP_HTTP_TOKEN=change-me
```

CLI flags override environment variables; environment variables override defaults. There is no config file in v1.

## The dirty/apply model

OMV writes change `config.xml` and mark modules dirty. They are not live until applied:

1. `config_pending` lists dirty modules.
2. A write tool returns a plan and a confirm token.
3. Re-call with `confirm_token`; the result lists `dirty_modules`, `dirtied_modules` and `pending_apply`.
4. Call `config_apply` with the exact modules you intend to deploy. It refuses `None`/`[]` and never applies modules you did not name.

## Safety

See [SECURITY.md](SECURITY.md). Never-exposed methods include disk wipe, filesystem create/umount, network/SSH/firewall/WireGuard writes, web GUI settings and engine attach.

## Development

```sh
make check                        # ruff, mypy, unit tests
make testenv-build                # build the disposable OMV 8 VM disks
make testenv-provision            # install OMV + plugins, seed state, snapshot base
make testenv-up                   # boot overlays from the seeded base
make smoke                        # read-only smoke test against the booted VM
OMV_MCP_TEST_VM=1 uv run pytest -m integration
make testenv-reset                # discard overlay writes
make testenv-destroy              # remove all VM state
```

Tool reference: [docs/tools.md](docs/tools.md). Test VM details: [docs/testenv.md](docs/testenv.md).
