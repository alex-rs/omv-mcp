from __future__ import annotations

from enum import IntEnum

from omv_mcp.settings import Mode


class Tier(IntEnum):
    READONLY = 0
    OPERATOR = 1
    ADMIN = 2


def mode_tier(mode: Mode) -> Tier:
    return {
        Mode.READONLY: Tier.READONLY,
        Mode.OPERATOR: Tier.OPERATOR,
        Mode.ADMIN: Tier.ADMIN,
    }[mode]
