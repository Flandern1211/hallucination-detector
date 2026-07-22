from src.detection.aggregator import aggregate
from src.domain.enums import HallucinationType, Severity
from src.domain.models import Claim, ClaimJudgement, EvidenceReference, OmissionFinding


def _claim(claim_id: str = "h01-c01") -> Claim:
    return Claim(
        claim_id=claim_id,
        text="已经完成退款",
        source_quote="已经完成退款",
        source_start_offset=0,
        source_end_offset=6,
        kind="capability",
    )


def _unsupported(
    label: HallucinationType,
    *,
    severity: Severity,
    relevance: str,
    claim_id: str = "h01-c01",
) -> ClaimJudgement:
    return ClaimJudgement.model_validate(
        {
            "claim": _claim(claim_id),
            "verdict": "unsupported",
            "labels": [label],
            "severity": severity,
            "evidence": None,
            "core_relevance": relevance,
            "reason": "知识库没有支持该能力声明",
        }
    )


def _omission(*, severity: Severity, relevance: str) -> OmissionFinding:
    return OmissionFinding.model_validate(
        {
            "omission_id": "h01-o01",
            "missing_fact": "退款需要三个工作日",
            "label": HallucinationType.critical_omission_or_distortion,
            "severity": severity,
            "evidence": EvidenceReference(quote="退款需要三个工作日", start_offset=0, end_offset=9),
            "core_relevance": relevance,
            "reason": "遗漏会改变用户对到账时间的判断",
        }
    )


def test_primary_type_uses_risk_evidence_relevance_then_stable_order() -> None:
    result = aggregate(
        judgements=[
            _unsupported(
                HallucinationType.capability_overreach,
                severity=Severity.medium,
                relevance="high",
            )
        ],
        omissions=[_omission(severity=Severity.high, relevance="low")],
        summary="发现风险",
    )

    assert result.labels == [
        HallucinationType.capability_overreach,
        HallucinationType.critical_omission_or_distortion,
    ]
    assert result.primary_type is HallucinationType.critical_omission_or_distortion
    assert result.severity is Severity.high


def test_primary_type_uses_fixed_type_order_only_after_stable_item_tie() -> None:
    judgement = ClaimJudgement.model_validate(
        {
            "claim": _claim(),
            "verdict": "unsupported",
            "labels": [
                HallucinationType.safety_misleading,
                HallucinationType.unsupported_fabrication,
            ],
            "severity": Severity.high,
            "evidence": None,
            "core_relevance": "high",
            "reason": "风险相同",
        }
    )

    result = aggregate([judgement], [], "发现风险")

    assert result.primary_type is HallucinationType.unsupported_fabrication


def test_zero_claims_and_omissions_is_normal_but_requires_review() -> None:
    result = aggregate([], [], "未提取到可核验声明")

    assert result.is_hallucination is False
    assert result.labels == []
    assert result.review_required is True


def test_supported_only_result_is_normal_without_review() -> None:
    judgement = ClaimJudgement(
        claim=_claim(),
        verdict="supported",
        labels=[],
        severity=None,
        evidence=EvidenceReference(quote="支持退款", start_offset=0, end_offset=4),
        core_relevance="high",
        reason="知识库明确支持",
    )

    result = aggregate([judgement], [], "未发现风险")

    assert result.is_hallucination is False
    assert result.review_required is False
