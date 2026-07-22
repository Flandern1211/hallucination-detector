from datetime import UTC
import math

import pytest

from src.domain.hashing import canonical_bytes, content_hash, utc_now
from src.domain.models import GroundTruthRecord


def test_canonical_hash_ignores_key_order_and_excluded_self_hash() -> None:
    assert content_hash({"b": 2, "a": "中文"}) == content_hash({"a": "中文", "b": 2})
    assert content_hash(
        {"a": 1, "artifact_hash": "x"}, frozenset({"artifact_hash"})
    ) == content_hash({"a": 1, "artifact_hash": "y"}, frozenset({"artifact_hash"}))


def test_canonical_bytes_are_compact_utf8_and_preserve_array_order() -> None:
    assert canonical_bytes({"值": [2, 1]}) == b'{"\xe5\x80\xbc":[2,1]}'
    assert canonical_bytes([1, 2]) != canonical_bytes([2, 1])


def test_canonical_bytes_reject_non_finite_numbers() -> None:
    with pytest.raises(ValueError, match="JSON compliant"):
        canonical_bytes({"score": math.nan})


def test_content_hash_is_lowercase_sha256_and_utc_now_is_aware() -> None:
    digest = content_hash({"a": 1})

    assert len(digest) == 64
    assert digest == digest.lower()
    assert set(digest) <= set("0123456789abcdef")
    assert utc_now().tzinfo is UTC


def test_canonical_hash_recursively_serializes_models_in_sequences() -> None:
    record = GroundTruthRecord(
        id="h01", is_hallucination=False, hallucination_type=None, detail="normal"
    )

    assert content_hash((record,)) == content_hash([record.model_dump(mode="json")])
