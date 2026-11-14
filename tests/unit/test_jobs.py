from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from omv_mcp.rpc.errors import OmvRpcError
from omv_mcp.rpc.jobs import JobRunner
from tests.unit.fakes import FakeBackend


class Ctx:
    def __init__(self) -> None:
        self.progress: list[tuple[float, float]] = []

    async def report_progress(self, *, progress: float, total: float) -> None:
        self.progress.append((progress, total))


async def test_start_requires_string() -> None:
    backend = FakeBackend({("A", "b"): 5})
    with pytest.raises(OmvRpcError, match="job filename"):
        await JobRunner(backend).start("A", "b")
    backend2 = FakeBackend({("A", "b"): "/tmp/job"})
    assert await JobRunner(backend2).start("A", "b") == "/tmp/job"


async def test_wait_accumulates_and_completes() -> None:
    state = {"calls": 0}

    def output(params: Mapping[str, Any] | None) -> dict[str, Any]:
        state["calls"] += 1
        if state["calls"] == 1:
            return {"output": "one\n", "pos": 4, "running": True, "pending_output": True}
        return {"output": "two\n", "pos": 8, "running": False, "pending_output": False}

    backend = FakeBackend({("Exec", "getOutput"): output})
    ctx = Ctx()
    result = await JobRunner(backend, poll_interval=0.01).wait("/tmp/job", 5, ctx)
    assert result.output == "one\ntwo\n"
    assert result.running is False
    assert ctx.progress


async def test_wait_timeout_returns_running() -> None:
    def output(params: Mapping[str, Any] | None) -> dict[str, Any]:
        return {"output": "still\n", "pos": 6, "running": True, "pending_output": False}

    backend = FakeBackend({("Exec", "getOutput"): output})
    result = await JobRunner(backend, poll_interval=0.01).wait("/tmp/job", 0.03)
    assert result.running is True
    assert "still" in result.output


async def test_job_error_includes_filename_and_tail() -> None:
    def output(params: Mapping[str, Any] | None) -> dict[str, Any]:
        return {"output": "boom\n", "pos": 5, "running": False, "error": "failed"}

    backend = FakeBackend({("Exec", "getOutput"): output})
    with pytest.raises(OmvRpcError, match="/tmp/job"):
        await JobRunner(backend).wait("/tmp/job", 5)


async def test_list_jobs_normalizes_strings() -> None:
    backend = FakeBackend({("Exec", "enumerate"): ["a", "b"]})
    assert await JobRunner(backend).list_jobs() == [{"filename": "a"}, {"filename": "b"}]


async def test_list_jobs_normalizes_mapping() -> None:
    backend = FakeBackend({("Exec", "enumerate"): {"/tmp/a": {"startTime": 1}, "/tmp/b": {}}})
    assert await JobRunner(backend).list_jobs() == [
        {"startTime": 1, "filename": "/tmp/a"},
        {"filename": "/tmp/b"},
    ]
