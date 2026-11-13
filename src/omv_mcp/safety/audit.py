from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from omv_mcp.rpc.redact import redact


class AuditLog:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    async def write(self, record: dict[str, Any]) -> None:
        payload = redact({"ts": datetime.now(UTC).isoformat(), **record})
        line = json.dumps(payload, default=str) + "\n"

        def append() -> None:
            created = not self._path.parent.exists()
            self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if created:
                self._path.parent.chmod(0o700)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line)
            self._path.chmod(0o600)

        async with self._lock:
            await asyncio.to_thread(append)
