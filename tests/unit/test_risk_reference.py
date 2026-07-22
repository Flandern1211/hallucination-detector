from src.domain.enums import HallucinationType, Severity
from src.domain.hashing import content_hash
from src.domain.models import (
    Claim,
    ClaimJudgement,
    ClassificationResult,
    GroundTruthRecord,
    RiskReference,
    SuccessfulPrediction,
)
from src.evaluation.evaluator import choose_risk_reference, evaluate, ground_truth_hash
from src.evaluation.type_mapping import TypeCompatibility


def _truth(record_id: str, positive: bool, kind: str | None = None) -> GroundTruthRecord:
    return GroundTruthRecord(
        id=record_id,
        is_hallucination=positive,
        hallucination_type=kind,
        detail="detail",
    )


def _success(
    record_id: str, positive: bool, primary: HallucinationType | None = None
) -> SuccessfulPrediction:
    if primary is None:
        result = ClassificationResult(
            is_hallucination=False,
            labels=[],
            primary_type=None,
            severity=None,
            review_required=True,
            claims=[],
            omissions=[],
            summary="result",
        )
    else:
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
        result = ClassificationResult(
            is_hallucination=True,
            labels=[primary],
            primary_type=primary,
            severity=Severity.medium,
            review_required=False,
            claims=[judgement],
            omissions=[],
            summary="result",
        )
    return SuccessfulPrediction(
        kind="success",
        id=record_id,
        result=result,
        engine="llm",
        model_name="model",
        detector_version="baseline-v1",
        config_hash="a" * 64,
        attempt_count=1,
    )


def _benchmark(records: list[GroundTruthRecord]) -> RiskReference:
    raw = {
        "schema_version": "1.0",
        "version": "benchmark-v1",
        "source": "frozen_benchmark_map",
        "ground_truth_hash": ground_truth_hash(records),
        "risk_rule_version": "risk-v1",
        "severity_by_positive_id": {"a": Severity.high, "b": Severity.medium},
    }
    return RiskReference.model_validate({**raw, "content_hash": content_hash(raw)})


def test_partial_uploaded_severity_never_falls_back_to_benchmark() -> None:
    records = [
        GroundTruthRecord(
            id="a",
            is_hallucination=True,
            hallucination_type="政策编造",
            detail="a",
            severity=Severity.high,
        ),
        _truth("b", True, "政策编造"),
    ]

    assert choose_risk_reference(records, _benchmark(records)) is None


def test_complete_uploaded_severity_builds_reference_and_high_risk_recall() -> None:
    records = [
        GroundTruthRecord(
            id="a",
            is_hallucination=True,
            hallucination_type="政策编造",
            detail="a",
            severity=Severity.high,
        ),
        GroundTruthRecord(
            id="b",
            is_hallucination=True,
            hallucination_type="政策编造",
            detail="b",
            severity=Severity.medium,
        ),
    ]
    reference = choose_risk_reference(records, None)
    assert reference is not None and reference.source == "uploaded_ground_truth"
    result = evaluate(
        [_success("a", False), _success("b", True, HallucinationType.knowledge_conflict)],
        records,
        reference,
        TypeCompatibility(
            schema_version="1.0",
            version="v1",
            mapping={"政策编造": [HallucinationType.knowledge_conflict]},
        ),
    )
    assert result.high_risk_recall.value == 0
    assert result.high_risk_recall.denominator == 1


def test_mismatched_or_incomplete_reference_makes_high_risk_recall_null() -> None:
    records = [_truth("a", True, "政策编造")]
    raw = {
        "schema_version": "1.0",
        "version": "bad-v1",
        "source": "frozen_benchmark_map",
        "ground_truth_hash": "0" * 64,
        "risk_rule_version": "risk-v1",
        "severity_by_positive_id": {"a": Severity.high},
    }
    bad = RiskReference.model_validate({**raw, "content_hash": content_hash(raw)})
    result = evaluate(
        [_success("a", True, HallucinationType.knowledge_conflict)],
        records,
        bad,
        TypeCompatibility(
            schema_version="1.0",
            version="v1",
            mapping={"政策编造": [HallucinationType.knowledge_conflict]},
        ),
    )
    assert result.high_risk_recall.value is None
    assert result.high_risk_recall.reason == "complete matching risk reference unavailable"
