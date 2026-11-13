from __future__ import annotations


class OmvRpcError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        service: str = "",
        method: str = "",
        trace: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.service = service
        self.method = method
        self.trace = trace

    def __str__(self) -> str:
        return f"OMV {self.service}.{self.method} failed ({self.code}): {self.message}"
