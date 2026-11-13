from __future__ import annotations

from fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    @mcp.prompt
    def health_check() -> str:
        return (
            "Call storage_health_summary, services_status and config_pending. "
            "Report warnings, dirty modules and reboot requirements. Do not apply changes."
        )

    @mcp.prompt
    def investigate_disk(devicefile: str) -> str:
        return (
            f"Call smart_disk for {devicefile} with section=all, then disks_list and "
            "filesystems_list filtered to that device. Summarize SMART health, temperature "
            "and usage. Do not run tests or wipe anything."
        )

    @mcp.prompt
    def prepare_share(name: str) -> str:
        return (
            f"Call shared_folder_candidates, then propose a shared_folder_create plan for {name}. "
            "Show the filesystem choice and side effects. Wait for a confirm token before executing."
        )
