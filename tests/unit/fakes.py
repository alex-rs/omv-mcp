from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from omv_mcp.rpc.base import RpcBackend


class FakeBackend(RpcBackend):
    def __init__(
        self,
        responses: Mapping[tuple[str, str], Any] | None = None,
        files: Mapping[tuple[str, str], bytes] | None = None,
    ) -> None:
        self.responses: dict[tuple[str, str], Any] = dict(responses or {})
        self.files: dict[tuple[str, str], bytes] = dict(files or {})
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.closed = False

    async def call(
        self,
        service: str,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        self.calls.append((service, method, dict(params or {})))
        value = self.responses.get((service, method))
        if isinstance(value, BaseException):
            raise value
        if callable(value):
            result = value(params)
            if inspect.isawaitable(result):
                return await result
            return result
        return value

    async def fetch_file(
        self,
        service: str,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> bytes:
        self.calls.append((service, method, dict(params or {})))
        key = (service, method)
        if key in self.files:
            return self.files[key]
        value = self.responses.get(key)
        if isinstance(value, BaseException):
            raise value
        if isinstance(value, bytes):
            return value
        raise AssertionError(f"no fake file for {key}")

    async def close(self) -> None:
        self.closed = True


def make_callable(
    fn: Callable[[Mapping[str, Any] | None], Any],
) -> Callable[[Mapping[str, Any] | None], Any]:
    return fn
