# Security

## Threat model

`omv-mcp` is an administrator-facing MCP server. It assumes the MCP client and the process environment are trusted. It protects against accidental destructive actions and secret leakage, not against a compromised MCP client or a malicious local user.

## Defaults

- Read-only mode.
- One SSH connection, host-key checking enabled, root login required in v1.
- HTTP transport binds `127.0.0.1` and requires `OMV_MCP_HTTP_TOKEN`.
- TLS verification is on unless explicitly disabled; a CA file implies verification.

## Writes

Every mutating tool:

1. Returns a plan with before/after changes, RPC calls, side effects and the current dirty modules.
2. Issues a 5-minute, single-use HMAC confirm token bound to the tool and canonical arguments.
3. Refuses execution if the dirty module set or the target object changed since the plan.
4. Applies only modules it dirtied, and only when `apply=True` was requested; `config_apply` requires an explicit list.
5. Writes a redacted JSONL audit record and enforces a mutation rate limit.

## Never exposed

Disk wipe, filesystem create/umount/mount-point changes, fstab writes, network interface/proxy writes, firewall writes, SSH writes, WireGuard writes, web GUI settings, user settings/password-by-context, certificate deletion/copy, compose engine commands, engine attach, apt/plugin uploads and environment-variable writes. `Cterm.*` is never exposed. `rpc_call` refuses these in every mode.

## Protected resources

By default, `user:root`, `user:admin`, group `users`, `sudo`, `ssh` and `_ssh` cannot be modified. Shared-folder deletion is refused while SMB, NFS, rsync, rsyncd or compose references it. Root filesystems are refused for snapshots.

## Secrets

Tool results, audit arguments and errors are recursively redacted: secret-named keys, URL credentials, `KEY=value` patterns and PEM private keys. Public SSH keys and public certificates are preserved. Logs, compose files and diagnostic reports are redacted as text and size-capped.

## HTTP transport

The bearer token is compared in constant time. A non-loopback bind without a token is rejected. Put a TLS-terminating reverse proxy in front of any non-local deployment.

## Reporting

Report vulnerabilities privately to the maintainer; do not include real NAS credentials, hostnames, disk serials or config captures in a public issue. Use the disposable test VM for reproduction.
