"""Immutable domain contracts for official evaluation metrics."""

from typing import Literal

from pydantic import Field

from src.domain.models import FrozenSequence, Sha256Hex, StrictModel


class MetricValue(StrictModel):
    value: float | None
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    reason: str | None = None


class EvaluationResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    ground_truth_hash: Sha256Hex
    matched_ids: FrozenSequence[str]
    prediction_only_ids: FrozenSequence[str]
    ground_truth_only_ids: FrozenSequence[str]
    failed_ids: FrozenSequence[str]
    evaluated_ids: FrozenSequence[str]
    false_positive_ids: FrozenSequence[str]
    false_negative_ids: FrozenSequence[str]
    tp: int = Field(ge=0)
    fp: int = Field(ge=0)
    tn: int = Field(ge=0)
    fn: int = Field(ge=0)
    precision: MetricValue
    recall: MetricValue
    f1: MetricValue
    specificity: MetricValue
    macro_f1: MetricValue
    balanced_accuracy: MetricValue
    type_match_rate: MetricValue
    high_risk_recall: MetricValue
    coverage: MetricValue
    unmappable_type_count: int = Field(ge=0)
    unmappable_types: FrozenSequence[str]
    complete: bool


def safe_ratio(numerator: int, denominator: int, reason: str) -> MetricValue:
    return MetricValue(
        value=None if denominator == 0 else numerator / denominator,
        numerator=numerator,
        denominator=denominator,
        reason=reason if denominator == 0 else None,
    )


__all__ = ["EvaluationResult", "MetricValue", "safe_ratio"]
