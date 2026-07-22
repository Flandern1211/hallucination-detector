"""Shared validation helpers for uploaded JSON batches."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import TypeVar, cast

from pydantic import BaseModel, ValidationError


_ILLEGAL_C0 = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
ModelT = TypeVar("ModelT", bound=BaseModel)


class PayloadTooLarge(ValueError):
    """Raised when an uploaded body exceeds the configured byte limit."""

    def __init__(self, maximum_bytes: int) -> None:
        self.maximum_bytes = maximum_bytes
        super().__init__(f"payload exceeds {maximum_bytes} bytes")


class InvalidJson(ValueError):
    """Raised when an uploaded body is not a valid JSON document."""


class BatchValidationError(ValueError):
    """Raised when a JSON batch violates a structural or record-level rule."""

    def __init__(self, paths: list[str], message: str) -> None:
        self.paths = tuple(dict.fromkeys(paths))
        super().__init__(message)


def decode_json_array(raw: bytes) -> list[object]:
    """Decode a strict JSON array without accepting non-standard constants."""

    def reject_constant(value: str) -> None:
        raise ValueError(f"invalid JSON constant {value}")

    try:
        value = cast(object, json.loads(raw, parse_constant=reject_constant))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise InvalidJson("payload must be valid UTF-8 JSON") from error
    if not isinstance(value, list):
        raise BatchValidationError(["$"], "payload must be a JSON array")
    return value


def validate_items(value: list[object], model: type[ModelT]) -> list[ModelT]:
    """Validate each item and expose Pydantic failures as JSONPath-like paths."""

    records: list[ModelT] = []
    paths: list[str] = []
    for index, item in enumerate(value):
        try:
            records.append(model.model_validate(item))
        except ValidationError as error:
            paths.extend(_validation_paths(index, item, error))
    if paths:
        raise BatchValidationError(paths, "batch contains invalid records")
    return records


def enforce_batch_size(records: Sequence[object], minimum: int, maximum: int) -> None:
    if not minimum <= len(records) <= maximum:
        raise BatchValidationError(["$"], f"batch must contain {minimum} to {maximum} records")


def enforce_unique_ids(records: list[ModelT]) -> None:
    seen: set[str] = set()
    duplicate_paths: list[str] = []
    for index, record in enumerate(records):
        record_id = cast(str, getattr(record, "id"))
        if record_id in seen:
            duplicate_paths.append(f"$[{index}].id")
        seen.add(record_id)
    if duplicate_paths:
        raise BatchValidationError(duplicate_paths, "record ids must be unique")


def _validation_paths(index: int, item: object, error: ValidationError) -> list[str]:
    paths: list[str] = []
    for detail in error.errors():
        location = detail["loc"]
        if location:
            paths.append(_location_path(index, location))
            continue
        message = str(detail["msg"])
        paths.extend(_root_error_paths(index, item, message))
    return paths


def _location_path(index: int, location: tuple[int | str, ...]) -> str:
    path = f"$[{index}]"
    for segment in location:
        path += f"[{segment}]" if isinstance(segment, int) else f".{segment}"
    return path


def _root_error_paths(index: int, item: object, message: str) -> list[str]:
    prefix = f"$[{index}]"
    field_names = (
        "user_question",
        "system_reply",
        "hallucination_type",
        "severity",
        "detail",
    )
    for field_name in field_names:
        if field_name in message:
            return [f"{prefix}.{field_name}"]
    if "illegal C0" in message:
        return _illegal_c0_paths(prefix, item) or [prefix]
    return [prefix]


def _illegal_c0_paths(path: str, value: object) -> list[str]:
    if isinstance(value, str):
        return [path] if _ILLEGAL_C0.search(value) else []
    if isinstance(value, Mapping):
        return [
            nested_path
            for key, nested in value.items()
            for nested_path in _illegal_c0_paths(f"{path}.{key}", nested)
        ]
    if isinstance(value, list):
        return [
            nested_path
            for nested_index, nested in enumerate(value)
            for nested_path in _illegal_c0_paths(f"{path}[{nested_index}]", nested)
        ]
    return []
