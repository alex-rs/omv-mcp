# Changelog

## 0.1.0

- Initial MCP server for OpenMediaVault 8 over SSH and HTTP.
- Read-only tool surface for system, storage, shares, access, jobs, network and plugins.
- Plan/confirm safety layer with HMAC tokens, audit JSONL, rate limiting, protected users/groups and never-exposed RPCs.
- Plans are audited; confirmed writes revalidate the target and expected dirty modules, and share updates preserve unspecified fields.
- Compose container logs use the container id/name OMV expects; cterm exec URLs are stripped from container listings.
- `apt_changelog` waits for OMV's background changelog job and returns its output; `writecache_flush` passes the required `rotate` parameter and waits for the flush job.
- Generic `rpc_call` refuses sensitive reads (WireGuard configs/QRs, certificate details, compose files, web-GUI local storage) and firewall rule deletion; `config_revert` is annotated destructive.
- Shared-folder deletion no longer fails when the compose plugin is not installed.
- Operator and admin writes for shares, users, jobs, packages, plugins, SMART, SnapRAID and writecache.
- `writecache_set` updates writecache settings in operator mode: partial settings are merged onto `getSettings` (the read-only `status` field is stripped), values are validated against the plugin's enums, and the write marks the `writecache` module dirty for `config_apply`.
- Disposable Docker/QEMU OMV 8 test VM with seeded production-like state.
- Pre-use hardening: plugin tools only register for installed packages; `Exec.isRunning` dict results are parsed correctly; `notifications_test_email` targets `EmailNotification`; SnapRAID array config uses its array UUID; confirm tokens bind actual secret values; cterm exec URLs are redacted; SSH retries only read-only RPCs; power actions do not probe after firing; `logs_list` pages server-side.
- Read-only list tools redact row contents, job filenames are validated before `Exec.*`, and generic `rpc_call` refuses config-database writes, Compose writes, Exec job internals, destructive snapshot/ACL methods, `Apt.upgrade` and environment-variable writes.
- `rpc_call` advertises `readOnlyHint=false` in admin mode, where it can execute non-read-only RPCs; generic `rpc_call` also refuses `Config.applyChanges*`/`revertChanges*` so config application stays behind `config_apply`/`config_revert`. `shared_folder_delete` plans now show the exact delete parameters (`recursive=false`), and `logs_list` is documented as a log-entry pager rather than a log-file list.
- Generic `rpc_call` now enforces the same guards as the dedicated tools: no recursive shared-folder deletes, no privileged user groups/system UIDs, no bulk user/group import, no dangerous SMB/NFS/rsyncd options, and no scheduled power actions unless `OMV_MCP_ALLOW_POWER=true`.
- Read-modify-write updates abort when the existing user, group or cron job cannot be read; only OMV's explicit "does not exist" response is treated as a create, so a transient read failure cannot reset SSH keys, email or other unspecified fields. Confirm now also refuses when the target disappeared since the plan was issued. `config_apply` reports the modules it applied, and the detected plugin set is carried into the app state.
- The HTTP backend logs out its OMV session on shutdown instead of leaving an authenticated web session alive until the server-side timeout.
