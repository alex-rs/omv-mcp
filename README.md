# omv-mcp

Safe MCP server for administering OpenMediaVault 8 over SSH or HTTP.

Read-only by default; every write is planned, confirmed, audited and applied only on request.
See `docs/tools.md` for the tool reference and `SECURITY.md` for the threat model.

Development targets a disposable OMV 8 VM in Docker only. See `docs/testenv.md`.
