import json

import pytest

from src.application.evaluation_service import EvaluationService, GroundTruthConflict
from src.domain.enums import HallucinationType, RunState, Severity
from src.domain.models import (
    Claim,
    ClaimJudgement,
    ClassificationResult,
    DetectionRunConfig,
    FailedPrediction,
    GroundTruthRecord,
    ReplyRecord,
    SuccessfulPrediction,
)
from src.evaluation.evaluator import evaluate
from src.evaluation.type_mapping import TypeCompatibility
from src.infrastructure.run_registry import RunRegistry


def _result(
    record_id: str, is_hallucination: bool, primary: HallucinationType | None = None
) -> ClassificationResult:
    if not is_hallucination:
        return ClassificationResult(
            is_hallucination=False,
            labels=[],
            primary_type=None,
            severity=None,
            review_required=True,
            claims=[],
            omissions=[],
            summary="normal",
        )
    assert primary is not None
    claim = Claim(
        claim_id=f"{record_id}-c01",
        text="claim",
        source_quote="claim",
        source_start_offset=0,
        source_end_offset=5,
        kind="fact",
    )
    judgement = ClaimJudgement(
        claim=claim,
        verdict="unsupported",
        labels=[primary],
        severity=Severity.medium,
        evidence=None,
        core_relevance="high",
        reason="unsupported",
    )
    return ClassificationResult(
        is_hallucination=True,
        labels=[primary],
        primary_type=primary,
        severity=Severity.medium,
        review_required=False,
        claims=[judgement],
        omissions=[],
        summary="positive",
    )


def _success(
    record_id: str, is_hallucination: bool, primary: HallucinationType | None = None
) -> SuccessfulPrediction:
    return SuccessfulPrediction(
        kind="success",
        id=record_id,
        result=_result(record_id, is_hallucination, primary),
        engine="llm",
        model_name="model",
        detector_version="baseline-v1",
        config_hash="a" * 64,
        attempt_count=1,
    )


def _failure(record_id: str) -> FailedPrediction:
    return FailedPrediction(
        kind="failure",
        id=record_id,
        error_code="timeout",
        error_summary="timeout",
        attempt_count=1,
        model_name="model",
    )


def _truth(record_id: str, positive: bool, kind: str | None = None) -> GroundTruthRecord:
    return GroundTruthRecord(
        id=record_id,
        is_hallucination=positive,
        hallucination_type=kind,
        detail="detail",
    )


def _type_map() -> TypeCompatibility:
    return TypeCompatibility(
        schema_version="1.0",
        version="test-v1",
        mapping={
            "政策编造": [HallucinationType.knowledge_conflict],
            "信息遗漏": [HallucinationType.critical_omission_or_distortion],
        },
    )


def test_metrics_exclude_failures_and_report_all_id_sets() -> None:
    result = evaluate(
        predictions=[
            _success("a", True, HallucinationType.knowledge_conflict),
            _success("b", False),
            _failure("c"),
            _success("x", False),
        ],
        ground_truth=[
            _truth("a", True, "政策编造"),
            _truth("b", True, "信息遗漏"),
            _truth("c", False),
            _truth("d", True, "安全误导"),
        ],
        risk_reference=None,
        type_map=_type_map(),
    )

    assert (result.tp, result.fp, result.tn, result.fn) == (1, 0, 0, 1)
    assert result.matched_ids == ["a", "b", "c"]
    assert result.evaluated_ids == ["a", "b"]
    assert result.failed_ids == ["c"]
    assert result.prediction_only_ids == ["x"]
    assert result.ground_truth_only_ids == ["d"]
    assert result.false_negative_ids == ["b"]
    assert result.coverage.value == pytest.approx(0.5)
    assert result.complete is False


def test_binary_metrics_and_zero_denominators_are_explicit() -> None:
    result = evaluate(
        [_success("a", False), _success("b", False)],
        [_truth("a", False), _truth("b", True, "政策编造")],
        None,
        _type_map(),
    )
    assert result.precision.value is None
    assert result.precision.reason == "no predicted positive records"
    assert result.recall.value == 0
    assert result.specificity.value == 1
    assert result.f1.value == 0
    assert result.macro_f1.value == pytest.approx(1 / 3)
    assert result.balanced_accuracy.value == pytest.approx(0.5)


def test_type_match_excludes_false_negatives_and_unknown_manual_types() -> None:
    result = evaluate(
        [
            _success("a", True, HallucinationType.knowledge_conflict),
            _success("b", False),
            _success("c", True, HallucinationType.knowledge_conflict),
        ],
        [
            _truth("a", True, "政策编造"),
            _truth("b", True, "信息遗漏"),
            _truth("c", True, "外部未知类型"),
        ],
        None,
        _type_map(),
    )
    assert result.type_match_rate.value == 1
    assert result.type_match_rate.denominator == 1
    assert result.unmappable_type_count == 1
    assert result.unmappable_types == ["外部未知类型"]


def test_evaluation_service_requires_frozen_run_and_never_replaces_ground_truth() -> None:
    registry = RunRegistry(uuid_factory=lambda: "run-1")
    record = ReplyRecord(id="a", user_question="q", system_reply="r", knowledge_base="")
    run = registry.create(
        records=[record],
        config=DetectionRunConfig(
            detector_version="baseline-v1", external_processing_acknowledged=True
        ),
        input_hash="a" * 64,
        detector_config_hash="b" * 64,
        provider_model="model",
    )
    raw = json.dumps(
        [
            {
                "id": "a",
                "is_hallucination": False,
                "hallucination_type": None,
                "detail": "normal",
            }
        ]
    ).encode()
    service = EvaluationService(registry, _type_map())
    with pytest.raises(RuntimeError, match="frozen"):
        service.load_ground_truth(run.id, raw, "load-1")

    registry.transition(run.id, RunState.running)
    registry.set_predictions(run.id, [_success("a", False)])
    registry.transition(run.id, RunState.frozen)
    first = service.load_ground_truth(run.id, raw, "load-1")
    assert service.load_ground_truth(run.id, raw, "load-1") == first
    with pytest.raises(GroundTruthConflict):
        service.load_ground_truth(
            run.id,
            raw.replace(b'"normal"', b'"different"'),
            "load-2",
        )
    assert service.evaluate(run.id, "eval-1").tn == 1
