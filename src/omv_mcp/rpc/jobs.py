from __future__ import annotations

import contextlib
import time
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from omv_mcp.rpc.base import RpcBackend
from omv_mcp.rpc.errors import OmvRpcError
from omv_mcp.rpc.redact import redact_text


class JobResult(BaseModel):
    filename: str
    running: bool = False
    output: str = ""
    pos: int = 0
    pending_output: bool = False
    error: str | None = None


class JobRunner:
    def __init__(
        self,
        backend: RpcBackend,
        poll_interval: float = 1.0,
        tail_bytes: int = 16384,
    ) -> None:
        self._backend = backend
        self._poll_interval = poll_interval
        self._tail_bytes = max(tail_bytes, 1024)

    async def start(
        self,
        service: str,
        method: str,
        params: Mapping[str, Any] | None = None,
    ) -> str:
        result = await self._backend.call(service, method, params)
        if not isinstance(result, str):
            raise OmvRpcError(f"{service}.{method} did not return a job filename")
        return result

    async def _output_once(self, filename: str, pos: int) -> dict[str, Any]:
        result = await self._backend.call(
            "Exec",
            "getOutput",
            {"filename": filename, "pos": pos, "length": self._tail_bytes},
        )
        if not isinstance(result, dict):
            raise OmvRpcError(f"Exec.getOutput returned {type(result).__name__}")
        if "pendingOutput" in result and "pending_output" not in result:
            result["pending_output"] = result["pendingOutput"]
        return result

    async def status(self, filename: str) -> bool:
        # Exec.isRunning unlinks the status/output files once the job is done,
        # so a read-only status check would destroy the output. Enumerate only
        # lists running jobs and leaves finished status files alone.
        return any(job.get("filename") == filename for job in await self.list_jobs())

    async def output(self, filename: str, pos: int = 0) -> JobResult:
        data = await self._output_once(filename, pos)
        return JobResult(
            filename=filename,
            running=bool(data.get("running")),
            output=str(data.get("output") or ""),
            pos=int(data.get("pos") or 0),
            pending_output=bool(data.get("pending_output")),
        )

    async def wait(
        self,
        filename: str,
        timeout: float,
        ctx: Any = None,
    ) -> JobResult:
        started = time.monotonic()
        pos = 0
        tail = ""
        while True:
            try:
                data = await self._output_once(filename, pos)
            except OmvRpcError as exc:
                raise OmvRpcError(
                    redact_text(f"job {filename} failed: {exc.message}; tail: {tail[-2000:]}"),
                    code=exc.code,
                    service=exc.service,
                    method=exc.method,
                ) from exc
            chunk = str(data.get("output") or "")
            if chunk:
                tail = (tail + chunk)[-self._tail_bytes :]
            pos = int(data.get("pos") or pos)
            running = bool(data.get("running"))
            pending = bool(data.get("pending_output"))
            error = data.get("error")
            if error:
                raise OmvRpcError(
                    redact_text(f"job {filename} failed: {error}; tail: {tail[-2000:]}")
                )
            elapsed = time.monotonic() - started
            if ctx is not None:
                with contextlib.suppress(Exception):
                    await ctx.report_progress(progress=elapsed, total=timeout)
            if not running and not pending:
                return JobResult(
                    filename=filename,
                    running=False,
                    output=tail,
                    pos=pos,
                    pending_output=False,
                )
            if elapsed >= timeout:
                return JobResult(
                    filename=filename,
                    running=True,
                    output=tail,
                    pos=pos,
                    pending_output=pending,
                )
            await _sleep(min(self._poll_interval, max(0.0, timeout - elapsed)))

    async def list_jobs(self) -> list[dict[str, Any]]:
        result = await self._backend.call("Exec", "enumerate")
        if isinstance(result, list):
            return [{"filename": item} if isinstance(item, str) else dict(item) for item in result]
        if isinstance(result, dict):
            return [
                ({**value, "filename": name} if isinstance(value, dict) else {"filename": name})
                for name, value in result.items()
            ]
        return []

    async def stop(self, filename: str) -> Any:
        return await self._backend.call("Exec", "stop", {"filename": filename})


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
