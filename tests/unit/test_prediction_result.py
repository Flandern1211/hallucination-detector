from datetime import UTC, datetime
import json
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from src.domain.enums import ArtifactStatus, HallucinationType, RunState, Severity
from src.domain.hashing import content_hash
from src.domain.models import (
    BaselineDetectorConfig,
    BatchDetectionResult,
    ClassificationResult,
    DetectionRunConfig,
    ErrorAnalysis,
    ExperimentalSuggestion,
    FailedErrorAnalysis,
    FailedPrediction,
    HumanReviewRevision,
    PredictionResult,
    ProviderUsage,
    SuccessfulErrorAnalysis,
    SuccessfulPrediction,
    SuggestionReport,
)


def _normal_result(*, review_required: bool = True) -> ClassificationResult:
    return ClassificationResult(
        is_hallucination=False,
        labels=[],
        primary_type=None,
        severity=None,
        review_required=review_required,
        claims=[],
        omissions=[],
        summary="无原子声明，需要复核",
    )


def _success() -> SuccessfulPrediction:
    return SuccessfulPrediction(
        kind="success",
        id="h01",
        result=_normal_result(),
        engine="llm",
        model_name="model",
        detector_version="baseline-v1",
        config_hash="config-hash",
        attempt_count=1,
    )


def test_state_enums_have_fixed_serialized_order() -> None:
    assert [state.value for state in RunState] == [
        "created",
        "running",
        "retryable_partial",
        "frozen",
        "abandoned",
    ]
    assert [state.value for state in ArtifactStatus] == [
        "not_started",
        "running",
        "completed",
        "failed",
    ]


def test_failed_prediction_rejects_classification_fields() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(PredictionResult).validate_python(
            {
                "kind": "failure",
                "id": "h01",
                "error_code": "timeout",
                "error_summary": "provider timeout",
                "attempt_count": 1,
                "model_name": None,
                "result": {"is_hallucination": False},
            }
        )


def test_prediction_union_accepts_exact_success_and_failure_shapes() -> None:
    adapter: TypeAdapter[PredictionResult] = TypeAdapter(PredictionResult)
    assert adapter.validate_python(_success()).kind == "success"
    failure = FailedPrediction(
        kind="failure",
        id="h02",
        error_code="request_budget_exhausted",
        error_summary="budget exhausted",
        attempt_count=0,
        model_name=None,
    )
    assert adapter.validate_python(failure).kind == "failure"


def test_batch_network_attempts_must_equal_record_attempts() -> None:
    failure = FailedPrediction(
        kind="failure",
        id="h02",
        error_code="timeout",
        error_summary="timeout",
        attempt_count=2,
        model_name="model",
    )
    values = {
        "schema_version": "1.0",
        "results": [_success(), failure],
        "input_hash": "input-hash",
        "detector_config_hash": "config-hash",
        "network_attempt_count": 3,
        "provider_usage": ProviderUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        "stopped_reason": None,
    }
    BatchDetectionResult.model_validate(values)
    with pytest.raises(ValidationError, match="network_attempt_count"):
        BatchDetectionResult.model_validate({**values, "network_attempt_count": 2})


def test_detection_run_config_requires_literal_acknowledgement() -> None:
    config = DetectionRunConfig(
        detector_version="baseline-v1", external_processing_acknowledged=True
    )
    assert config.manual_review_enabled is False
    with pytest.raises(ValidationError, match="external_processing_acknowledged"):
        DetectionRunConfig.model_validate(
            {"detector_version": "baseline-v1", "external_processing_acknowledged": False}
        )


def test_human_revision_validates_event_chain_hash_and_serializes_utc_as_z() -> None:
    timestamp = datetime(2026, 7, 22, 1, 2, 3, tzinfo=UTC)
    body = {
        "schema_version": "1.0",
        "review_id": "review-1",
        "run_id": "run-1",
        "record_id": "h01",
        "status": "confirmed_correct",
        "source_prediction_hash": "prediction-hash",
        "reviewed_result": _normal_result().model_dump(mode="json"),
        "changed_fields": [],
        "revision_number": 1,
        "save_request_id": "request-1",
        "created_at_utc": "2026-07-22T01:02:03Z",
        "previous_event_hash": None,
    }
    event_hash = content_hash(body)
    revision = HumanReviewRevision(
        schema_version="1.0",
        review_id="review-1",
        run_id="run-1",
        record_id="h01",
        status="confirmed_correct",
        source_prediction_hash="prediction-hash",
        reviewed_result=_normal_result(),
        changed_fields=[],
        revision_number=1,
        save_request_id="request-1",
        created_at_utc=timestamp,
        previous_event_hash=None,
        event_hash=event_hash,
    )

    assert revision.model_dump(mode="json")["created_at_utc"] == "2026-07-22T01:02:03Z"
    with pytest.raises(ValidationError, match="event_hash"):
        HumanReviewRevision.model_validate_json(
            json.dumps(
                {**revision.model_dump(mode="json"), "event_hash": "0" * 64},
                ensure_ascii=False,
            )
        )
    with pytest.raises(ValidationError, match="previous_event_hash"):
        HumanReviewRevision.model_validate_json(
            json.dumps(
                {
                    **revision.model_dump(mode="json"),
                    "revision_number": 2,
                    "previous_event_hash": None,
                },
                ensure_ascii=False,
            )
        )


def test_baseline_config_requires_exact_definition_key_sets() -> None:
    config: dict[str, Any] = {
        "schema_version": "1.0",
        "version": "baseline-v1",
        "claim_extraction_system_prompt": "claim",
        "evidence_judgement_system_prompt": "evidence",
        "completeness_check_system_prompt": "omission",
        "error_analysis_system_prompt": "analysis",
        "suggestion_system_prompt": "suggestion",
        "hallucination_type_definitions": {
            item.value: f"definition-{index}"
            for index, item in enumerate(HallucinationType, start=1)
        },
        "severity_definitions": {item.value: f"severity-{item.value}" for item in Severity},
        "max_claims": 10,
        "temperature": 0,
        "provider_response_schema_version": "1.0",
    }
    BaselineDetectorConfig.model_validate_json(json.dumps(config, ensure_ascii=False))
    label_definitions = config["hallucination_type_definitions"]
    assert isinstance(label_definitions, dict)
    del label_definitions["知识冲突"]
    with pytest.raises(ValidationError, match="hallucination_type_definitions"):
        BaselineDetectorConfig.model_validate_json(json.dumps(config, ensure_ascii=False))


def test_error_analysis_union_and_secondary_reason_invariants() -> None:
    analysis = SuccessfulErrorAnalysis(
        kind="success",
        case_ref="case-001",
        error_kind="false_negative",
        primary_reason="claim_not_extracted",
        secondary_reasons=["evidence_misread", "evidence_misread"],
        evidence="依据",
        proposed_improvement="改进",
    )
    assert analysis.secondary_reasons == ["evidence_misread"]
    assert TypeAdapter(ErrorAnalysis).validate_python(analysis).kind == "success"
    failure = FailedErrorAnalysis(
        kind="failure", case_ref="case-002", error_code="timeout", error_summary="timeout"
    )
    assert TypeAdapter(ErrorAnalysis).validate_python(failure).kind == "failure"
    with pytest.raises(ValidationError, match="primary_reason"):
        SuccessfulErrorAnalysis(
            kind="success",
            case_ref="case-001",
            error_kind="false_negative",
            primary_reason="claim_not_extracted",
            secondary_reasons=["claim_not_extracted"],
            evidence="依据",
            proposed_improvement="改进",
        )


def test_suggestion_limits_and_report_contract() -> None:
    analysis = SuccessfulErrorAnalysis(
        kind="success",
        case_ref="case-001",
        error_kind="false_positive",
        primary_reason="non_factual_expression_false_positive",
        secondary_reasons=[],
        evidence="依据",
        proposed_improvement="改进",
    )
    suggestion = ExperimentalSuggestion(
        suggestion_id="suggestion-001",
        category="prompt_principle",
        target_stage="claim_extraction",
        rationale="理由",
        proposed_change="变更原则",
        known_risks=["可能过度过滤"],
    )
    report = SuggestionReport(
        schema_version="1.0",
        run_id="run-1",
        label_source="official_ground_truth",
        input_hash="input-hash",
        prediction_hash="prediction-hash",
        detector_version="baseline-v1",
        detector_config_hash="config-hash",
        model_name="model",
        generated_at_utc=datetime(2026, 7, 22, tzinfo=UTC),
        coverage=1.0,
        warning="小样本实验性建议，不代表效果提升",
        analyses=[analysis],
        suggestions=[suggestion],
    )
    assert report.model_dump(mode="json")["generated_at_utc"].endswith("Z")

    with pytest.raises(ValidationError):
        SuggestionReport.model_validate({**report.model_dump(mode="json"), "coverage": 1.01})
    with pytest.raises(ValidationError, match="known_risks"):
        ExperimentalSuggestion(
            suggestion_id="suggestion-001",
            category="prompt_principle",
            target_stage="claim_extraction",
            rationale="理由",
            proposed_change="变更原则",
            known_risks=[],
        )
