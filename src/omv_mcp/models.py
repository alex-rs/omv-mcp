from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    total: int
    count: int
    offset: int
    limit: int
    items: list[T]
    truncated: bool = False
    note: str | None = None


class Change(BaseModel):
    field: str
    before: Any = None
    after: Any = None


class PlanResponse(BaseModel):
    status: Literal["plan"] = "plan"
    tool: str
    rpc_calls: list[dict[str, Any]]
    before: Any = None
    after: Any = None
    changes: list[Change] = []
    side_effects: dict[str, Any] = {}
    dirty_modules: list[str]
    modules_expected: list[str]
    confirm_token: str
    expires_at: str


class OperationResult(BaseModel):
    status: Literal["executed"] = "executed"
    tool: str
    result: Any = None
    job_id: str | None = None
    dirty_modules: list[str]
    dirtied_modules: list[str]
    pending_apply: list[str]
    applied_modules: list[str] = []
    next_step: str | None = None


class FsHealth(BaseModel):
    uuid: str | None = None
    devicefile: str
    label: str | None = None
    type: str | None = None
    mounted: bool = False
    used_percent: float | None = None
    status: str


class DiskHealth(BaseModel):
    devicename: str
    devicefile: str
    model: str | None = None
    size_h: str | None = None
    temperature: int | None = None
    smart_status: str | None = None
    power_on_hours: int | None = None
    status: str


class ServiceHealth(BaseModel):
    name: str
    title: str | None = None
    enabled: bool = False
    running: bool = False
    status: str


class HealthSummary(BaseModel):
    hostname: str
    version: str
    reboot_required: bool
    dirty_modules: list[str]
    available_pkg_updates: int
    filesystems: list[FsHealth]
    disks: list[DiskHealth]
    services: list[ServiceHealth]
    warnings: list[str]
