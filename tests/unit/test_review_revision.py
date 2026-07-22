from datetime import UTC, datetime
from typing import Literal, cast

import pytest

from src.application.review_service import (
    ConfirmedResultMismatch,
    ReviewDisabled,
    ReviewSaveRequest,
    ReviewService,
    ReviewTargetUnavailable,
    SourcePredictionConflict,
)
from src.domain.enums import HallucinationType, RunState, Severity
from src.domain.hashing import content_hash
from src.domain.models import (
    Claim,
    ClaimJudgement,
    ClassificationResult,
    DetectionRunConfig,
    EvidenceReference,
    FailedPrediction,
    ReplyRecord,
    SuccessfulPrediction,
)
from src.infrastructure.run_registry import RunRecord, RunRegistry
from src.review.revision_store import RevisionStore


def _normal_result(summary: str = "正常") -> ClassificationResult:
    claim = Claim(
        claim_id="h01-c01",
        text="支持退货",
        source_quote="支持退货",
        source_start_offset=0,
        source_end_offset=4,
        kind="policy",
    )
    judgement = ClaimJudgement(
        claim=claim,
        verdict="supported",
        labels=[],
        severity=None,
        evidence=EvidenceReference(quote="七天", start_offset=0, end_offset=2),
        core_relevance="high",
        reason="有依据",
    )
    return ClassificationResult(
        is_hallucination=False,
        labels=[],
        primary_type=None,
        severity=None,
        review_required=False,
        claims=[judgement],
        omissions=[],
        summary=summary,
    )


def _corrected_result() -> ClassificationResult:
    original = _normal_result()
    judgement = original.claims[0].model_copy(
        update={
            "verdict": "unsupported",
            "labels": [HallucinationType.unsupported_fabrication],
            "severity": Severity.medium,
            "evidence": None,
            "reason": "知识库没有依据",
        }
    )
    return ClassificationResult(
        is_hallucination=True,
        labels=[HallucinationType.unsupported_fabrication],
        primary_type=HallucinationType.unsupported_fabrication,
        severity=Severity.medium,
        review_required=False,
        claims=[judgement],
        omissions=[],
        summary="存在无依据编造",
    )


def _service(
    *, enabled: bool = True, failed: bool = False
) -> tuple[ReviewService, RunRecord, SuccessfulPrediction | FailedPrediction]:
    registry = RunRegistry(uuid_factory=lambda: "run-1")
    record = ReplyRecord(
        id="h01", user_question="问题", system_reply="支持退货", knowledge_base="七天可退货"
    )
    run = registry.create(
        records=[record],
        config=DetectionRunConfig(
            detector_version="baseline-v1",
            manual_review_enabled=enabled,
            external_processing_acknowledged=True,
        ),
        input_hash="a" * 64,
        detector_config_hash="b" * 64,
        provider_model="model",
    )
    prediction: SuccessfulPrediction | FailedPrediction
    if failed:
        prediction = FailedPrediction(
            kind="failure",
            id="h01",
            error_code="timeout",
            error_summary="timeout",
            attempt_count=1,
            model_name="model",
        )
    else:
        prediction = SuccessfulPrediction(
            kind="success",
            id="h01",
            result=_normal_result(),
            engine="llm",
            model_name="model",
            detector_version="baseline-v1",
            config_hash="b" * 64,
            attempt_count=1,
        )
    registry.transition(run.id, RunState.running)
    registry.set_predictions(run.id, [prediction])
    registry.transition(run.id, RunState.frozen)
    service = ReviewService(
        registry,
        RevisionStore(),
        uuid_factory=iter(["review-1", "review-2", "review-3"]).__next__,
        clock=lambda: datetime(2026, 7, 23, 1, 2, 3, tzinfo=UTC),
    )
    return service, run, prediction


def _request(
    request_id: str,
    prediction: SuccessfulPrediction,
    *,
    status: Literal["confirmed_correct", "corrected"] = "confirmed_correct",
    result: ClassificationResult | None = None,
) -> ReviewSaveRequest:
    return ReviewSaveRequest(
        status=status,
        save_request_id=request_id,
        source_prediction_hash=content_hash(prediction),
        reviewed_result=result or prediction.result,
    )


def test_confirm_and_correct_append_hash_chained_revisions_without_mutating_prediction() -> None:
    service, run, prediction = _service()
    assert isinstance(prediction, SuccessfulPrediction)
    original_hash = run.prediction_hash

    first = service.save(run.id, "h01", _request("save-1", prediction))
    second = service.save(
        run.id,
        "h01",
        _request("save-2", prediction, status="corrected", result=_corrected_result()),
    )

    assert first.revision_number == 1 and first.previous_event_hash is None
    assert second.revision_number == 2 and second.previous_event_hash == first.event_hash
    assert second.changed_fields == [
        "/is_hallucination",
        "/labels",
        "/primary_type",
        "/severity",
        "/claims",
        "/summary",
    ]
    assert run.prediction_hash == original_hash


def test_save_request_is_idempotent_and_source_hash_conflicts() -> None:
    service, run, prediction = _service()
    assert isinstance(prediction, SuccessfulPrediction)
    request = _request("save-1", prediction)

    assert service.save(run.id, "h01", request) == service.save(run.id, "h01", request)
    with pytest.raises(SourcePredictionConflict):
        service.save(
            run.id,
            "h01",
            request.model_copy(
                update={"save_request_id": "save-2", "source_prediction_hash": "0" * 64}
            ),
        )


def test_review_rejects_disabled_failed_and_mismatched_confirmation() -> None:
    disabled, disabled_run, disabled_prediction = _service(enabled=False)
    assert isinstance(disabled_prediction, SuccessfulPrediction)
    with pytest.raises(ReviewDisabled):
        disabled.save(disabled_run.id, "h01", _request("save-1", disabled_prediction))

    failed_service, failed_run, failed_prediction = _service(failed=True)
    assert isinstance(failed_prediction, FailedPrediction)
    with pytest.raises(ReviewTargetUnavailable):
        failed_service.save(
            failed_run.id,
            "h01",
            ReviewSaveRequest(
                status="confirmed_correct",
                save_request_id="save-1",
                source_prediction_hash="a" * 64,
                reviewed_result=_normal_result(),
            ),
        )

    service, run, prediction = _service()
    assert isinstance(prediction, SuccessfulPrediction)
    with pytest.raises(ConfirmedResultMismatch):
        service.save(
            run.id,
            "h01",
            _request("save-1", prediction, result=_corrected_result()),
        )


def test_corrected_result_revalidates_evidence_and_aggregate() -> None:
    service, run, prediction = _service()
    assert isinstance(prediction, SuccessfulPrediction)
    valid_result = _normal_result()
    evidence = cast(EvidenceReference, valid_result.claims[0].evidence)
    invalid_judgement = valid_result.claims[0].model_copy(
        update={"evidence": evidence.model_copy(update={"quote": "错误"})}
    )
    invalid_evidence = valid_result.model_copy(update={"claims": [invalid_judgement]})
    with pytest.raises(ValueError, match="evidence"):
        service.save(
            run.id,
            "h01",
            _request("save-1", prediction, status="corrected", result=invalid_evidence),
        )

    invalid_aggregate = _corrected_result().model_copy(update={"severity": Severity.high})
    with pytest.raises(ValueError, match="aggregate"):
        service.save(
            run.id,
            "h01",
            _request("save-2", prediction, status="corrected", result=invalid_aggregate),
        )


def test_restore_is_new_monotonic_event_and_snapshot_excludes_failures() -> None:
    service, run, prediction = _service()
    assert isinstance(prediction, SuccessfulPrediction)
    service.save(
        run.id,
        "h01",
        _request("save-1", prediction, status="corrected", result=_corrected_result()),
    )
    restored = service.restore_original(run.id, "h01", "restore-1", content_hash(prediction))
    snapshot = service.review_snapshot(run.id)

    assert restored.revision_number == 2
    assert restored.reviewed_result == prediction.result
    assert snapshot.reviewed_success_count == 1
    assert snapshot.total_success_count == 1
    assert snapshot.unreviewed_ids == []
    assert snapshot.current_revisions == [restored]
