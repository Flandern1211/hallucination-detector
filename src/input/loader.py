"""Read and validate reply and official ground-truth upload batches."""

from __future__ import annotations

from src.domain.hashing import content_hash
from src.domain.models import GroundTruthRecord, ReplyRecord
from src.input.validator import (
    BatchValidationError,
    InvalidJson,
    PayloadTooLarge,
    decode_json_array,
    enforce_batch_size,
    enforce_unique_ids,
    validate_items,
)


MAX_BODY_BYTES = 5 * 1024 * 1024
MAX_RECORDS = 20
MAX_BATCH_TEXT_CHARS = 200_000


def load_reply_batch(raw: bytes) -> list[ReplyRecord]:
    """Validate an uploaded reply batch while preserving record order and text."""

    _enforce_body_size(raw)
    records = validate_items(decode_json_array(raw), ReplyRecord)
    enforce_batch_size(records, 1, MAX_RECORDS)
    enforce_unique_ids(records)
    total_characters = sum(
        len(record.user_question) + len(record.system_reply) + len(record.knowledge_base)
        for record in records
    )
    if total_characters > MAX_BATCH_TEXT_CHARS:
        raise BatchValidationError(["$"], "batch text exceeds 200000 characters")
    return records


def load_ground_truth_batch(raw: bytes) -> list[GroundTruthRecord]:
    """Validate an uploaded official ground-truth batch without modifying it."""

    _enforce_body_size(raw)
    records = validate_items(decode_json_array(raw), GroundTruthRecord)
    enforce_batch_size(records, 1, MAX_RECORDS)
    enforce_unique_ids(records)
    return records


def reply_input_hash(records: list[ReplyRecord]) -> str:
    """Return the canonical hash for the normalized, order-preserving reply batch."""

    return content_hash([record.model_dump(mode="json") for record in records])


def _enforce_body_size(raw: bytes) -> None:
    if len(raw) > MAX_BODY_BYTES:
        raise PayloadTooLarge(MAX_BODY_BYTES)


__all__ = [
    "MAX_BATCH_TEXT_CHARS",
    "MAX_BODY_BYTES",
    "MAX_RECORDS",
    "BatchValidationError",
    "InvalidJson",
    "PayloadTooLarge",
    "load_ground_truth_batch",
    "load_reply_batch",
    "reply_input_hash",
]
