# AGENTS.md

Guidance for AI coding agents (and humans) working on **omv-mcp**, an MCP server for administering [OpenMediaVault](https://www.openmediavault.org) 8 safely.

## Project at a glance
- Python ≥ 3.12, managed with `uv`. Package in `src/omv_mcp/`, entry point `omv-mcp`.
- Talks to OMV through its JSON-RPC API, either over SSH (`omv-rpc`, preferred) or over HTTP (`rpc.php`).
- Safety first: read-only by default, operator/admin modes, plan → confirm for every write, audit log, secret redaction.
- Development and integration tests run against a **disposable OMV 8 VM inside Docker** (`testenv/`), never against a real NAS.

If a `plan/` directory exists locally, read `plan/PLAN.md` first. It's the implementation plan and is intentionally not committed (see "Public repo hygiene"). Don't recreate it in tracked files.

## Layout
```
src/omv_mcp/     server code (rpc/ backends, safety/, tools/, shaping, settings)
src/omv_mcp/schemas/  bundled OMV RPC param schemas (generic OMV files)
tests/           unit tests (FakeBackend + fixtures), integration tests (test VM only)
testenv/         Docker + QEMU OMV 8 test VM: Dockerfile, compose.yaml, run-vm.sh, cloud-init, seed.py
docs/            public docs (tools.md is generated, testenv.md, SECURITY.md)
plan/            INTERNAL, gitignored: plan, reference captures, private notes
```

## Commands
```sh
uv sync                          # install deps
uv run ruff check . && uv run ruff format --check .
uv run pyright                   # or mypy, whichever the project uses
uv run pytest                    # unit tests, offline
make testenv-up                  # boot the OMV test VM (127.0.0.1:2222 ssh, :8080 web)
make testenv-reset               # fresh overlays from the seeded base snapshot
uv run pytest -m integration     # integration tests against the test VM
uv run omv-mcp --backend ssh --host 127.0.0.1 --port 2222 --mode readonly
```
Keep the Makefile, README and this section in sync when commands change.

## Hard rules
1. **Only the test VM.** The only OMV instance you may connect to is the local Docker test VM (`127.0.0.1`, ports 2222/8080, hostname `omv-test`). Never SSH, curl, ping or RPC any other host, especially a real/production NAS, even read-only, even if credentials are lying around. If you need information about a real system, ask the maintainer.
2. **Writes only inside the test VM.** Destructive tests (wipe, format, power, apply) only run there, after `make testenv-reset`. Integration fixtures and `testenv/` scripts must keep their host/hostname guard. Never weaken or bypass it.
3. **Never expose dangerous OMV methods** that the plan lists as never-exposed (disk wipe, filesystem create/umount, network/SSH/firewall/WireGuard writes, etc.) without an explicit maintainer decision.
4. **Every mutating tool** goes through the safety layer: plan → confirm token, audit record, and reporting of pending (dirty) modules. Never call `Config.applyChanges` implicitly, and never apply modules the tool didn't dirty itself.
5. Verify RPC method names and params against the OMV sources and datamodels **in the test VM** (`/usr/share/openmediavault/engined/rpc/*.inc`, `/usr/share/openmediavault/datamodels/rpc.*.json`). Don't guess.

## Public repo hygiene
This repository is **public**. Before every commit, check that nothing private is staged:
- No real hostnames, IPs, MAC addresses, disk UUIDs or serials, share/user names, or personal names/emails from any real installation. Use generic examples (`nas.example.lan`, `192.0.2.10`, `tester`).
- No secrets: passwords, tokens, SSH keys, certificates, `.env` files. The test VM's generated keys and admin password live in `testenv/.state/` (gitignored). Runtime config belongs in env vars or `~/.config/omv-mcp/`.
- Plans, research notes, reference captures and TODO lists for the maintainer go in `plan/` (gitignored). Don't move their contents into tracked docs or code comments.
- Fixtures come from the test VM only. Still run the redactor on them.
- Run `gitleaks protect --staged` (or the pre-commit hook, once set up) and `git status --ignored` to confirm `plan/` and `testenv/.state/` stay untracked. Never `git add -f` an ignored path.

## Commits
- **Commit regularly**: small, focused commits, at least one per finished step (e.g. "backend + tests", "disks tools", "testenv seed"). Don't let large uncommitted work pile up.
- Every commit must pass lint, type check and unit tests. Integration tests must pass before a feature is marked done.
- Use [Conventional Commits](https://www.conventionalcommits.org): `feat(tools): add smart_disk`, `fix(rpc): re-login on session expiry`, `test:`, `docs:`, `chore:`, `refactor:`, `ci:`.
- Message body: what changed and why, plus any OMV quirk discovered. No secrets or private details in messages.
- Work on `main` with small commits, or short-lived branches for larger features. Don't rewrite published history. Push only when the maintainer has set up a remote and asked for it.

## Adding a tool (checklist)
1. Find the RPC in the test VM sources and read its params schema.
2. Choose a tier (readonly / operator / admin) and set annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`).
3. Shape the output: pagination (`limit`/`offset`), field projection, size cap, humanized units, secrets redacted.
4. For writes: plan output (before/after diff, modules dirtied, side effects), confirm token, audit log, `pending_apply` in the result.
5. Unit test with FakeBackend fixtures, and an integration test against the test VM for writes.
6. Regenerate `docs/tools.md`, update the README if user-facing, then commit.

## Code style
- Type hints everywhere, `ruff` formatting, async I/O (`httpx`, `asyncssh`).
- Tool descriptions are short, factual and state side effects ("writes config; needs config_apply").
- Errors: raise `OmvRpcError` with the OMV message. Never leak PHP traces or secrets into tool output.
