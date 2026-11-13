from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from omv_mcp.safety.guard import SafetyError


def canonical_args(args: dict[str, Any]) -> str:
    cleaned = {
        key: value
        for key, value in args.items()
        if key not in {"confirm_token", "ctx"} and not key.startswith("_")
    }
    return json.dumps(cleaned, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class IssuedPlan:
    tool: str
    args: str
    expires_at: float
    plan: Any


class ConfirmManager:
    def __init__(
        self,
        secret: bytes,
        ttl_seconds: int = 300,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._secret = secret
        self._ttl = ttl_seconds
        self._now = now
        self._issued: dict[str, IssuedPlan] = {}
        self._lock = asyncio.Lock()

    def _signature(self, tool: str, args: str, expiry: int) -> str:
        message = f"{tool}\n{args}\n{expiry}".encode()
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    async def issue(self, tool: str, args: dict[str, Any], plan: Any) -> tuple[str, float]:
        expiry = int(self._now() + self._ttl)
        encoded = canonical_args(args)
        token = f"{expiry}.{self._signature(tool, encoded, expiry)}"
        async with self._lock:
            self._issued[token] = IssuedPlan(tool, encoded, float(expiry), plan)
        return token, float(expiry)

    async def consume(self, token: str, tool: str, args: dict[str, Any]) -> Any:
        try:
            expiry_text, signature = token.split(".", 1)
            expiry = int(expiry_text)
        except (ValueError, AttributeError) as exc:
            raise SafetyError("invalid confirm token") from exc
        encoded = canonical_args(args)
        async with self._lock:
            issued = self._issued.get(token)
            if issued is None:
                raise SafetyError("invalid confirm token")
            if self._now() > issued.expires_at:
                raise SafetyError("confirm token expired")
            if issued.tool != tool:
                raise SafetyError("confirm token was issued for a different tool")
            if issued.args != encoded:
                raise SafetyError("confirm token arguments do not match this call")
            expected = self._signature(tool, encoded, expiry)
            if not hmac.compare_digest(signature, expected):
                raise SafetyError("invalid confirm token")
            self._issued.pop(token, None)
        return issued.plan
