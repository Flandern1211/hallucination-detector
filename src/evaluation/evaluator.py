"""Pure official-ground-truth evaluation."""

from __future__ import annotations

from src.domain.enums import Severity
from src.domain.hashing import content_hash
from src.domain.metrics import EvaluationResult, MetricValue, safe_ratio
from src.domain.models import (
    FailedPrediction,
    GroundTruthRecord,
    PredictionResult,
    RiskReference,
    SuccessfulPrediction,
)
from src.evaluation.type_mapping import TypeCompatibility


def ground_truth_hash(records: list[GroundTruthRecord]) -> str:
    normalized: list[dict[str, object]] = []
    for record in records:
        item: dict[str, object] = {
            "id": record.id,
            "is_hallucination": record.is_hallucination,
            "hallucination_type": record.hallucination_type,
            "detail": record.detail,
        }
        if record.severity is not None:
            item["severity"] = record.severity
        normalized.append(item)
    return content_hash(normalized)


def choose_risk_reference(
    ground_truth: list[GroundTruthRecord], benchmark: RiskReference | None
) -> RiskReference | None:
    positives = [record for record in ground_truth if record.is_hallucination]
    supplied = [record for record in positives if record.severity is not None]
    source_hash = ground_truth_hash(ground_truth)
    if supplied:
        if len(supplied) != len(positives):
            return None
        raw = {
            "schema_version": "1.0",
            "version": "uploaded-v1",
            "source": "uploaded_ground_truth",
            "ground_truth_hash": source_hash,
            "risk_rule_version": "uploaded-severity-v1",
            "severity_by_positive_id": {
                record.id: record.severity for record in positives if record.severity is not None
            },
        }
        return RiskReference.model_validate({**raw, "content_hash": content_hash(raw)})
    positive_ids = {record.id for record in positives}
    if (
        benchmark is not None
        and benchmark.ground_truth_hash == source_hash
        and set(benchmark.severity_by_positive_id) == positive_ids
    ):
        return benchmark
    return None


def _nullable_mean(first: MetricValue, second: MetricValue, reason: str) -> MetricValue:
    if first.value is None or second.value is None:
        return MetricValue(value=None, numerator=0, denominator=2, reason=reason)
    return MetricValue(value=(first.value + second.value) / 2, numerator=2, denominator=2)


def evaluate(
    predictions: list[PredictionResult],
    ground_truth: list[GroundTruthRecord],
    risk_reference: RiskReference | None,
    type_map: TypeCompatibility,
) -> EvaluationResult:
    prediction_by_id = {prediction.id: prediction for prediction in predictions}
    truth_by_id = {record.id: record for record in ground_truth}
    matched_ids = [prediction.id for prediction in predictions if prediction.id in truth_by_id]
    prediction_only_ids = [
        prediction.id for prediction in predictions if prediction.id not in truth_by_id
    ]
    ground_truth_only_ids = [
        record.id for record in ground_truth if record.id not in prediction_by_id
    ]
    failed_ids = [
        record_id
        for record_id in matched_ids
        if isinstance(prediction_by_id[record_id], FailedPrediction)
    ]
    evaluated_ids = [
        record_id
        for record_id in matched_ids
        if isinstance(prediction_by_id[record_id], SuccessfulPrediction)
    ]

    tp = fp = tn = fn = 0
    false_positive_ids: list[str] = []
    false_negative_ids: list[str] = []
    for record_id in evaluated_ids:
        prediction = prediction_by_id[record_id]
        assert isinstance(prediction, SuccessfulPrediction)
        predicted = prediction.result.is_hallucination
        actual = truth_by_id[record_id].is_hallucination
        if predicted and actual:
            tp += 1
        elif predicted:
            fp += 1
            false_positive_ids.append(record_id)
        elif actual:
            fn += 1
            false_negative_ids.append(record_id)
        else:
            tn += 1

    precision = safe_ratio(tp, tp + fp, "no predicted positive records")
    recall = safe_ratio(tp, tp + fn, "no official positive records in evaluated intersection")
    specificity = safe_ratio(tn, tn + fp, "no official normal records in evaluated intersection")
    f1 = safe_ratio(2 * tp, 2 * tp + fp + fn, "positive-class F1 denominator is zero")
    negative_f1 = safe_ratio(2 * tn, 2 * tn + fp + fn, "negative-class F1 denominator is zero")
    macro_f1 = _nullable_mean(f1, negative_f1, "one or more class F1 values are undefined")
    balanced_accuracy = _nullable_mean(recall, specificity, "recall or specificity is undefined")

    type_numerator = type_denominator = 0
    unmappable_types: list[str] = []
    for record_id in evaluated_ids:
        truth = truth_by_id[record_id]
        prediction = prediction_by_id[record_id]
        assert isinstance(prediction, SuccessfulPrediction)
        if not truth.is_hallucination or truth.hallucination_type is None:
            continue
        compatible = type_map.compatible_types(truth.hallucination_type)
        if compatible is None:
            if truth.hallucination_type not in unmappable_types:
                unmappable_types.append(truth.hallucination_type)
            continue
        if not prediction.result.is_hallucination or prediction.result.primary_type is None:
            continue
        type_denominator += 1
        type_numerator += int(prediction.result.primary_type in compatible)
    type_match_rate = safe_ratio(
        type_numerator, type_denominator, "no dual-positive mappable records"
    )

    source_hash = ground_truth_hash(ground_truth)
    positive_ids = {record.id for record in ground_truth if record.is_hallucination}
    reference_complete = (
        risk_reference is not None
        and risk_reference.ground_truth_hash == source_hash
        and set(risk_reference.severity_by_positive_id) == positive_ids
    )
    if reference_complete and risk_reference is not None:
        high_ids = [
            record.id
            for record in ground_truth
            if risk_reference.severity_by_positive_id.get(record.id) is Severity.high
        ]
        high_detected = 0
        for record_id in high_ids:
            high_prediction = prediction_by_id.get(record_id)
            if (
                isinstance(high_prediction, SuccessfulPrediction)
                and high_prediction.result.is_hallucination
            ):
                high_detected += 1
        high_risk_recall = safe_ratio(
            high_detected, len(high_ids), "no official high-risk positive records"
        )
    else:
        high_risk_recall = MetricValue(
            value=None,
            numerator=0,
            denominator=0,
            reason="complete matching risk reference unavailable",
        )

    coverage = safe_ratio(len(evaluated_ids), len(ground_truth), "empty ground truth")
    return EvaluationResult(
        ground_truth_hash=source_hash,
        matched_ids=matched_ids,
        prediction_only_ids=prediction_only_ids,
        ground_truth_only_ids=ground_truth_only_ids,
        failed_ids=failed_ids,
        evaluated_ids=evaluated_ids,
        false_positive_ids=false_positive_ids,
        false_negative_ids=false_negative_ids,
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        specificity=specificity,
        macro_f1=macro_f1,
        balanced_accuracy=balanced_accuracy,
        type_match_rate=type_match_rate,
        high_risk_recall=high_risk_recall,
        coverage=coverage,
        unmappable_type_count=sum(
            1
            for record_id in evaluated_ids
            if truth_by_id[record_id].is_hallucination
            and truth_by_id[record_id].hallucination_type in unmappable_types
        ),
        unmappable_types=unmappable_types,
        complete=coverage.value == 1.0,
    )


__all__ = ["choose_risk_reference", "evaluate", "ground_truth_hash"]
