from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any

from omv_mcp.models import Page

_UNITS = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")


def human_bytes(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number < 0:
        return str(value)
    for unit in _UNITS:
        if number < 1024 or unit == _UNITS[-1]:
            return f"{number:.1f} {unit}" if unit != "B" else f"{int(number)} B"
        number /= 1024
    return f"{number:.1f} PiB"


def human_duration(value: Any) -> str:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return str(value)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def project_fields(item: dict[str, Any], fields: Sequence[str] | str | None) -> dict[str, Any]:
    if fields is None or fields == "all":
        return dict(item)
    return {field: item.get(field) for field in fields}


def filter_sort_slice(
    items: Iterable[dict[str, Any]],
    *,
    search: str | None = None,
    sort: str | None = None,
    order: str = "asc",
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    rows = list(items)
    if search:
        needle = search.casefold()
        rows = [
            row for row in rows if any(needle in str(value).casefold() for value in row.values())
        ]
    if sort:
        rows.sort(key=lambda row: str(row.get(sort, "")), reverse=order == "desc")
    total = len(rows)
    return total, rows[offset : offset + limit]


def shape_page(
    items: list[dict[str, Any]],
    *,
    total: int,
    offset: int,
    limit: int,
    max_bytes: int,
    note: str | None = None,
) -> Page[dict[str, Any]]:
    kept = list(items)
    capped = False
    page = Page(
        total=total,
        count=len(kept),
        offset=offset,
        limit=limit,
        items=kept,
        truncated=len(kept) < total,
        note=note,
    )
    if not kept:
        return page
    while kept:
        page.items = kept
        page.count = len(kept)
        page.truncated = len(kept) < total or capped
        page.note = note or ("response capped; narrow fields or page further" if capped else None)
        payload = json.dumps(page.model_dump(), default=str).encode()
        if len(payload) <= max_bytes:
            return page
        kept = kept[:-1]
        capped = True
    page.items = []
    page.count = 0
    page.truncated = True
    page.note = "response capped; narrow fields or page further"
    return page
