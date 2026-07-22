from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.application.suggestion_service import (
    NoAnalyzableErrors,
    SuggestionConflict,
    SuggestionRequest,
    SuggestionService,
)
from src.domain.enums import HallucinationType, RunState, Severity
from src.domain.hashing import content_hash
from src.domain.models import (
    ClassificationResult,
    EvidenceReference,
    FailedErrorAnalysis,
    GroundTruthRecord,
    HumanReviewRevision,
    OmissionFinding,
    ProviderUsage,
    SuccessfulErrorAnalysis,
    SuccessfulPrediction,
)
from src.providers.base import ProviderCallResult
from src.suggestions.error_analyzer import (
    HumanRevisionSource,
    InvalidErrorAnalysis,
    LabelSourceIneligible,
    OfficialSource,
    build_cases,
    validate_analyses,
)


_HASH = "a" * 64


def _classification(is_hallucination: bool) -> ClassificationResult:
    if not is_hallucination:
        return ClassificationResult(
            is_hallucination=False,
            labels=[],
            primary_type=None,
            severity=None,
            review_required=True,
            claims=[],
            omissions=[],
            summary="需要复核",
        )
    return ClassificationResult(
        is_hallucination=True,
        labels=[HallucinationType.critical_omission_or_distortion],
        primary_type=HallucinationType.critical_omission_or_distortion,
        severity=Severity.high,
        review_required=False,
        claims=[],
        omissions=[
            OmissionFinding(
                omission_id="omission-001",
                missing_fact="必须说明限制",
                label="关键遗漏或歪曲",
                severity=Severity.high,
                evidence=EvidenceReference(quote="限制", start_offset=0, end_offset=2),
                core_relevance="high",
                reason="会改变用户判断",
            )
        ],
        summary="存在关键遗漏",
    )


def _prediction(record_id: str, is_hallucination: bool) -> SuccessfulPrediction:
    return SuccessfulPrediction(
        kind="success",
        id=record_id,
        result=_classification(is_hallucination),
        engine="llm",
        model_name="model-a",
        detector_version="baseline-v1",
        config_hash=_HASH,
        attempt_count=1,
    )


def _run() -> SimpleNamespace:
    records = (
        SimpleNamespace(
            id="h03", user_question="问题三", system_reply="回复三", knowledge_base="限制"
        ),
        SimpleNamespace(
            id="h11", user_question="问题十一", system_reply="回复十一", knowledge_base="限制"
        ),
    )
    predictions = (_prediction("h03", False), _prediction("h11", True))
    return SimpleNamespace(
        id="run-1",
        state=RunState.frozen,
        records=records,
        predictions=predictions,
        input_hash=_HASH,
        prediction_hash=content_hash(predictions),
        detector_config_hash=_HASH,
        config=SimpleNamespace(manual_review_enabled=True),
    )


def _official_source(*, make_errors: bool = True) -> OfficialSource:
    return OfficialSource(
        labels=(
            GroundTruthRecord(
                id="h03",
                is_hallucination=make_errors,
                hallucination_type="知识冲突" if make_errors else None,
                detail="标注理由" if make_errors else "",
                severity=Severity.high if make_errors else None,
            ),
            GroundTruthRecord(
                id="h11",
                is_hallucination=False if make_errors else True,
                hallucination_type=None if make_errors else "关键遗漏或歪曲",
                detail="" if make_errors else "标注理由",
                severity=None if make_errors else Severity.high,
            ),
        ),
        coverage=1.0,
    )


def _analysis(case_ref: str, error_kind: str) -> SuccessfulErrorAnalysis:
    return SuccessfulErrorAnalysis.model_validate(
        {
            "kind": "success",
            "case_ref": case_ref,
            "error_kind": error_kind,
            "primary_reason": "claim_not_extracted",
            "secondary_reasons": [],
            "evidence": "归因依据",
            "proposed_improvement": "通用改进原则",
        }
    )


def _revision(run_id: str, prediction: SuccessfulPrediction) -> HumanReviewRevision:
    body = {
        "schema_version": "1.0",
        "review_id": f"review-{prediction.id}",
        "run_id": run_id,
        "record_id": prediction.id,
        "status": "confirmed_correct",
        "source_prediction_hash": content_hash(prediction),
        "reviewed_result": prediction.result,
        "changed_fields": [],
        "revision_number": 1,
        "save_request_id": f"save-{prediction.id}",
        "created_at_utc": datetime(2026, 7, 23, tzinfo=UTC),
        "previous_event_hash": None,
    }
    hash_body = {
        **body,
        "created_at_utc": "2026-07-23T00:00:00Z",
        "reviewed_result": prediction.result.model_dump(mode="json"),
    }
    return HumanReviewRevision.model_validate({**body, "event_hash": content_hash(hash_body)})


def test_case_refs_follow_prediction_order_and_hide_record_ids() -> None:
    cases = build_cases(_run(), _official_source())

    assert [case.case_ref for case in cases.items] == ["case-001", "case-002"]
    assert "h03" not in str(cases.provider_payload())
    assert cases.record_id_by_case_ref == {"case-001": "h03", "case-002": "h11"}


def test_analysis_must_match_case_set_order_and_error_kind() -> None:
    cases = build_cases(_run(), _official_source())

    with pytest.raises(InvalidErrorAnalysis):
        validate_analyses(cases.items, [_analysis("case-002", "false_positive")])
    with pytest.raises(InvalidErrorAnalysis):
        validate_analyses(
            cases.items,
            [
                _analysis("case-002", "false_positive"),
                _analysis("case-001", "false_negative"),
            ],
        )


def test_analysis_failure_stops_the_complete_analysis_set() -> None:
    cases = build_cases(_run(), _official_source())
    failed = FailedErrorAnalysis(
        kind="failure",
        case_ref="case-002",
        error_code="timeout",
        error_summary="timed out",
    )

    with pytest.raises(InvalidErrorAnalysis, match="failed"):
        validate_analyses(cases.items, [_analysis("case-001", "false_negative"), failed])


def test_official_source_requires_complete_coverage_and_all_prediction_ids() -> None:
    with pytest.raises(LabelSourceIneligible, match="100%"):
        build_cases(_run(), OfficialSource(labels=_official_source().labels, coverage=0.5))
    with pytest.raises(LabelSourceIneligible, match="ids"):
        build_cases(_run(), OfficialSource(labels=_official_source().labels[:1], coverage=1.0))


def test_human_source_requires_complete_reviews_and_current_prediction_hashes() -> None:
    run = _run()
    revisions = tuple(_revision(run.id, prediction) for prediction in run.predictions)
    cases = build_cases(
        run,
        HumanRevisionSource(
            revisions=revisions,
            total_success_count=2,
            reviewed_success_count=2,
        ),
    )
    assert cases.label_source == "human_revision"

    with pytest.raises(LabelSourceIneligible, match="100%"):
        build_cases(
            run,
            HumanRevisionSource(
                revisions=revisions[:1], total_success_count=2, reviewed_success_count=1
            ),
        )

    stale = revisions[0].model_copy(update={"source_prediction_hash": "0" * 64})
    with pytest.raises(LabelSourceIneligible, match="stale"):
        build_cases(
            run,
            HumanRevisionSource(
                revisions=(stale, revisions[1]), total_success_count=2, reviewed_success_count=2
            ),
        )


def test_no_false_positive_or_false_negative_returns_empty_cases() -> None:
    assert build_cases(_run(), _official_source(make_errors=False)).items == ()


class _Provider:
    def __init__(self, *, invalid_analyses: bool = False) -> None:
        self.analysis_calls = 0
        self.suggestion_calls = 0
        self.invalid_analyses = invalid_analyses

    def analyze_errors(self, cases, detector, budget):  # type: ignore[no-untyped-def]
        self.analysis_calls += 1
        budget.before_request()
        analyses = [
            _analysis(case.case_ref, case.error_kind)
            for case in (cases[:1] if self.invalid_analyses else cases)
        ]
        return ProviderCallResult(
            value=analyses,
            model_name="model-a",
            usage=ProviderUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            attempts=1,
            repaired=False,
        )

    def generate_suggestions(self, analyses, detector, label_source, budget):  # type: ignore[no-untyped-def]
        from src.domain.models import ExperimentalSuggestionBody

        self.suggestion_calls += 1
        budget.before_request()
        return ProviderCallResult(
            value=[
                ExperimentalSuggestionBody(
                    category="prompt_principle",
                    target_stage="evidence_judgement",
                    rationale="使用通用证据边界",
                    proposed_change="对缺少证据的确定性事实采用更保守的标签边界",
                    known_risks=["可能增加人工复核数量"],
                )
            ],
            model_name="model-a",
            usage=ProviderUsage(prompt_tokens=8, completion_tokens=4, total_tokens=12),
            attempts=1,
            repaired=False,
        )


def _detector() -> SimpleNamespace:
    return SimpleNamespace(version="baseline-v1")


def test_suggestion_service_saves_only_a_fully_validated_report(tmp_path: Path) -> None:
    from src.infrastructure.artifact_store import ArtifactStore

    provider = _Provider()
    run = _run()
    service = SuggestionService(
        registry=cast(Any, SimpleNamespace(get=lambda run_id: run)),
        provider=cast(Any, provider),
        detector=cast(Any, _detector()),
        label_source_resolver=lambda run_id, source: _official_source(),
        artifact_store=ArtifactStore(tmp_path / "runtime"),
        uuid_factory=lambda: "suggestion-fixed-id",
        wall_clock=lambda: datetime(2026, 7, 23, tzinfo=UTC),
    )

    summary = service.start(
        run.id,
        SuggestionRequest(
            label_source="official_ground_truth", external_processing_acknowledged=True
        ),
    )

    assert summary.status == "completed"
    assert provider.analysis_calls == provider.suggestion_calls == 1
    assert service.get_report(run.id).suggestions[0].suggestion_id == "suggestion-fixed-id"
    assert (tmp_path / "runtime" / run.id / "suggestions" / "suggestion_report.json").is_file()
    with pytest.raises(SuggestionConflict):
        service.start(
            run.id,
            SuggestionRequest(
                label_source="official_ground_truth", external_processing_acknowledged=True
            ),
        )


def test_no_errors_make_zero_provider_calls_and_invalid_analysis_saves_no_report(
    tmp_path: Path,
) -> None:
    from src.infrastructure.artifact_store import ArtifactStore

    no_error_provider = _Provider()
    run = _run()
    no_error_service = SuggestionService(
        registry=cast(Any, SimpleNamespace(get=lambda run_id: run)),
        provider=cast(Any, no_error_provider),
        detector=cast(Any, _detector()),
        label_source_resolver=lambda run_id, source: _official_source(make_errors=False),
        artifact_store=ArtifactStore(tmp_path / "none"),
    )
    with pytest.raises(NoAnalyzableErrors):
        no_error_service.start(
            run.id,
            SuggestionRequest(
                label_source="official_ground_truth", external_processing_acknowledged=True
            ),
        )
    assert no_error_provider.analysis_calls == no_error_provider.suggestion_calls == 0

    invalid_provider = _Provider(invalid_analyses=True)
    invalid_service = SuggestionService(
        registry=cast(Any, SimpleNamespace(get=lambda run_id: run)),
        provider=cast(Any, invalid_provider),
        detector=cast(Any, _detector()),
        label_source_resolver=lambda run_id, source: _official_source(),
        artifact_store=ArtifactStore(tmp_path / "invalid"),
    )
    summary = invalid_service.start(
        run.id,
        SuggestionRequest(
            label_source="official_ground_truth", external_processing_acknowledged=True
        ),
    )
    assert summary.status == "failed"
    assert invalid_provider.analysis_calls == 1
    assert invalid_provider.suggestion_calls == 0
    assert not (tmp_path / "invalid" / run.id / "suggestions" / "suggestion_report.json").exists()
