from __future__ import annotations

import re
from typing import Any

_SECRET_KEY_PARTS = (
    "pass",
    "pwd",
    "secret",
    "token",
    "api_key",
    "private_key",
    "privatekey",
    "shared_key",
    "preshared_key",
    "presharedkey",
    "apikey",
    "psk",
    "ssh_key",
    "wpapsk",
    "httppassword",
    "execurl",
)
_REDACTED = "***"
_PEM_PRIVATE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_URL_CREDENTIALS = re.compile(
    r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<user>[^/\s:@]+):(?P<pw>[^/\s@]+)@"
)
_NAMES = "|".join(map(re.escape, _SECRET_KEY_PARTS))
_KEY_VALUE = re.compile(
    r"(?P<key>[A-Za-z0-9_.-]*(?:" + _NAMES + r")"
    r"[A-Za-z0-9_.-]*)\s*(?P<sep>[=:])\s*(?P<val>[^\s,;]+)",
    re.IGNORECASE,
)
_JSON_VALUE = re.compile(
    r'"(?P<key>[^"]*(?:' + _NAMES + r')[^"]*)"\s*:\s*"(?P<val>(?:\\.|[^"\\])*)"',
    re.IGNORECASE,
)
_XML_VALUE = re.compile(
    r"(?P<open><(?P<tag>[^>]*(?:" + _NAMES + r")[^>]*)>)(?P<val>.*?)(?P<close></[^>]+>)",
    re.IGNORECASE | re.DOTALL,
)


def _secret_key(key: object) -> bool:
    text = str(key).lower().replace("-", "_")
    return any(part in text for part in _SECRET_KEY_PARTS)


def redact_text(text: str) -> str:
    text = _PEM_PRIVATE.sub("-----BEGIN PRIVATE KEY-----\n***\n-----END PRIVATE KEY-----", text)
    text = _URL_CREDENTIALS.sub(
        lambda m: f"{m.group('scheme')}{m.group('user')}:{_REDACTED}@", text
    )
    text = _JSON_VALUE.sub(lambda m: f'"{m.group("key")}": "{_REDACTED}"', text)
    text = _XML_VALUE.sub(lambda m: f"{m.group('open')}{_REDACTED}{m.group('close')}", text)
    return _KEY_VALUE.sub(lambda m: f"{m.group('key')}{m.group('sep')}{_REDACTED}", text)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            if _secret_key(key):
                out[key] = _REDACTED
            else:
                out[key] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value
