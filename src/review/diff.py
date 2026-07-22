from __future__ import annotations

from typing import Any

from src.domain.models import ClassificationResult


_FIELD_ORDER = (
    "is_hallucination",
    "labels",
    "primary_type",
    "severity",
    "review_required",
    "claims",
    "omissions",
    "summary",
)


def diff_results(before: ClassificationResult, after: ClassificationResult) -> list[str]:
    before_data = before.model_dump(mode="json")
    after_data = after.model_dump(mode="json")
    return [
        f"/{field}" for field in _FIELD_ORDER if before_data.get(field) != after_data.get(field)
    ]


def model_equal(left: Any, right: Any) -> bool:
    if hasattr(left, "model_dump") and hasattr(right, "model_dump"):
        return bool(left.model_dump(mode="json") == right.model_dump(mode="json"))
    return bool(left == right)
