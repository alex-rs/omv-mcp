from __future__ import annotations

import json
from importlib import resources
from typing import Any


def read_catalog() -> dict[str, Any]:
    try:
        text = resources.files(__package__).joinpath("catalog.json").read_text()
    except (FileNotFoundError, ModuleNotFoundError):
        return {"source": "unavailable", "services": {}}
    data = json.loads(text)
    return data if isinstance(data, dict) else {"source": "invalid", "services": {}}


def read_schema(service: str) -> dict[str, Any] | None:
    name = f"rpc.{service.lower()}.json"
    try:
        text = resources.files(__package__).joinpath(name).read_text()
    except (FileNotFoundError, ModuleNotFoundError):
        return None
    data = json.loads(text)
    return data if isinstance(data, dict) else None
