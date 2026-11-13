from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class RpcBackend(Protocol):
    async def call(
        self,
        service: str,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any: ...

    async def fetch_file(
        self,
        service: str,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> bytes: ...

    async def close(self) -> None: ...
