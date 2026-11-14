# Changelog

## 0.1.0

- Initial MCP server for OpenMediaVault 8 over SSH and HTTP.
- Read-only tool surface for system, storage, shares, access, jobs, network and plugins.
- Plan/confirm safety layer with HMAC tokens, audit JSONL, rate limiting, protected users/groups and never-exposed RPCs.
- Plans are audited; confirmed writes revalidate the target and expected dirty modules, and share updates preserve unspecified fields.
- Compose container logs use the container id/name OMV expects; cterm exec URLs are stripped from container listings.
- Operator and admin writes for shares, users, jobs, packages, plugins, SMART, SnapRAID and writecache.
- Disposable Docker/QEMU OMV 8 test VM with seeded production-like state.
