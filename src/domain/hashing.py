from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import hashlib
import json
from typing import Any


def canonical_bytes(value: Any, exclude: frozenset[str] = frozenset()) -> bytes:
    raw = _json_value(value)
    if isinstance(raw, Mapping):
        raw = {key: item for key, item in raw.items() if key not in exclude}
    return json.dumps(
        raw,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _json_value(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    return value


def content_hash(value: Any, exclude: frozenset[str] = frozenset()) -> str:
    return hashlib.sha256(canonical_bytes(value, exclude)).hexdigest()


def utc_now() -> datetime:
    return datetime.now(UTC)
