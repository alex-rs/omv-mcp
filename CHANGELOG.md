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
- Disposable Docker/QEMU OMV 8 test VM with seeded production-like state.
