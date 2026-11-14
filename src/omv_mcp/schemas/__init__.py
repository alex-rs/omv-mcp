from __future__ import annotations

import json
import re
from importlib import resources
from typing import Any

_SERVICE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def read_catalog() -> dict[str, Any]:
    try:
        text = resources.files(__package__).joinpath("catalog.json").read_text()
    except (FileNotFoundError, ModuleNotFoundError):
        return {"source": "unavailable", "services": {}}
    data = json.loads(text)
    return data if isinstance(data, dict) else {"source": "invalid", "services": {}}


def read_schema(service: str) -> dict[str, Any] | None:
    if not _SERVICE_RE.fullmatch(service):
        return None
    name = f"rpc.{service.lower()}.json"
    try:
        text = resources.files(__package__).joinpath(name).read_text()
    except (FileNotFoundError, ModuleNotFoundError):
        return None
    data = json.loads(text)
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {
            str(entry["id"]): entry
            for entry in data
            if isinstance(entry, dict) and isinstance(entry.get("id"), str)
        }
    return None
