from __future__ import annotations

from omv_mcp.shaping import (
    filter_sort_slice,
    human_bytes,
    human_duration,
    project_fields,
    shape_page,
)


def test_human_units() -> None:
    assert human_bytes(4 * 1024**4) == "4.0 TiB"
    assert human_duration(3600) == "1h 0m"
    assert human_duration(90) == "1m 30s"


def test_projection_semantics() -> None:
    item = {"a": 1, "b": 2}
    assert project_fields(item, None) == item
    assert project_fields(item, "all") == item
    assert project_fields(item, ["a", "missing"]) == {"a": 1, "missing": None}


def test_filter_sort_slice() -> None:
    rows = [{"name": "B"}, {"name": "a"}, {"name": "c"}]
    total, out = filter_sort_slice(rows, search="a", sort="name", order="desc")
    assert total == 1
    assert out == [{"name": "a"}]
    total, out = filter_sort_slice(rows, sort="name", limit=2)
    assert total == 3
    assert out == [{"name": "B"}, {"name": "a"}]


def test_page_cap_drops_items() -> None:
    page = shape_page([{"x": "y" * 100}] * 10, total=10, offset=0, limit=10, max_bytes=1000)
    assert page.truncated is True
    assert page.count < 10
    assert page.note
