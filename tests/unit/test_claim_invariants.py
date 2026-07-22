from typing import Any

import pytest
from pydantic import ValidationError

from src.domain.enums import HallucinationType, Severity
from src.domain.models import (
    Claim,
    ClaimJudgement,
    ClassificationResult,
    EvidenceReference,
    OmissionFinding,
    ReplyRecord,
    validate_claim_quote,
)


def _claim() -> Claim:
    return Claim(
        claim_id="h01-c01",
        text="支持七天退货",
        source_quote="支持七天退货",
        source_start_offset=3,
        source_end_offset=9,
        kind="policy",
    )


def _evidence() -> EvidenceReference:
    return EvidenceReference(quote="七天", start_offset=0, end_offset=2)


def _supported() -> ClaimJudgement:
    return ClaimJudgement(
        claim=_claim(),
        verdict="supported",
        labels=[],
        severity=None,
        evidence=_evidence(),
        core_relevance="high",
        reason="知识库支持",
    )


def test_enum_values_have_the_fixed_serialized_order() -> None:
    assert [item.value for item in HallucinationType] == [
        "知识冲突",
        "无依据编造",
        "能力越界",
        "安全误导",
        "关键遗漏或歪曲",
    ]
    assert [item.value for item in Severity] == ["高", "中", "低"]


def test_reply_record_normalizes_only_id_and_forbids_unknown_fields() -> None:
    record = ReplyRecord(
        id="  h01  ", user_question=" 问题 ", system_reply=" 回复 ", knowledge_base=" 知识 "
    )

    assert record.id == "h01"
    assert record.user_question == " 问题 "
    assert record.system_reply == " 回复 "
    assert record.knowledge_base == " 知识 "
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ReplyRecord(
            id="h01",
            user_question="问题",
            system_reply="回复",
            knowledge_base="",
            unexpected="value",  # type: ignore[call-arg]
        )


@pytest.mark.parametrize("record_id", ["", " bad/id ", "-leading", "a" * 129])
def test_reply_record_rejects_unsafe_normalized_ids(record_id: str) -> None:
    with pytest.raises(ValidationError, match="id"):
        ReplyRecord(id=record_id, user_question="问题", system_reply="回复", knowledge_base="")


def test_reply_text_boundaries_and_illegal_c0_are_enforced_without_truncation() -> None:
    ReplyRecord(id="h01", user_question="q" * 10_000, system_reply="r", knowledge_base="k" * 50_000)
    ReplyRecord(id="h02", user_question="q", system_reply="r\n\t", knowledge_base="")

    for field, value in (
        ("user_question", "q" * 10_001),
        ("system_reply", "r" * 10_001),
        ("knowledge_base", "k" * 50_001),
        ("system_reply", "bad\x01reply"),
    ):
        values = {
            "id": "h01",
            "user_question": "q",
            "system_reply": "r",
            "knowledge_base": "",
        }
        values[field] = value
        with pytest.raises(ValidationError):
            ReplyRecord.model_validate(values)

    with pytest.raises(ValidationError, match="must not be blank"):
        ReplyRecord(id="h01", user_question=" \n ", system_reply="r", knowledge_base="")


def test_claim_and_evidence_must_match_unicode_code_point_slices() -> None:
    reply = "答复🙂支持七天退货"
    claim = _claim()
    validate_claim_quote(claim, reply)
    with pytest.raises(ValueError, match="source_quote"):
        validate_claim_quote(claim.model_copy(update={"source_end_offset": 8}), reply)


def test_claim_rejects_invalid_offset_ranges_and_output_limits() -> None:
    values = _claim().model_dump()
    values["source_end_offset"] = values["source_start_offset"]
    with pytest.raises(ValidationError, match="source_end_offset"):
        Claim.model_validate(values)

    Claim.model_validate({**_claim().model_dump(), "text": "x" * 5_000})
    with pytest.raises(ValidationError, match="at most 5000"):
        Claim.model_validate({**_claim().model_dump(), "text": "x" * 5_001})


@pytest.mark.parametrize(
    ("verdict", "labels", "severity", "evidence"),
    [
        ("supported", [], None, None),
        ("supported", [HallucinationType("知识冲突")], None, _evidence()),
        ("contradicted", [], Severity("高"), _evidence()),
        ("unsupported", [HallucinationType("无依据编造")], Severity("中"), _evidence()),
        ("unverifiable", [], Severity("低"), None),
    ],
)
def test_claim_judgement_rejects_verdict_field_mismatches(
    verdict: str,
    labels: list[HallucinationType],
    severity: Severity | None,
    evidence: EvidenceReference | None,
) -> None:
    with pytest.raises(ValidationError, match="verdict"):
        ClaimJudgement(
            claim=_claim(),
            verdict=verdict,  # type: ignore[arg-type]
            labels=labels,
            severity=severity,
            evidence=evidence,
            core_relevance="high",
            reason="reason",
        )


def test_claim_labels_are_deduplicated_and_saved_in_fixed_order() -> None:
    judgement = ClaimJudgement(
        claim=_claim(),
        verdict="unsupported",
        labels=[
            HallucinationType("能力越界"),
            HallucinationType("知识冲突"),
            HallucinationType("能力越界"),
        ],
        severity=Severity("高"),
        evidence=None,
        core_relevance="high",
        reason="reason",
    )

    assert judgement.labels == [
        HallucinationType("知识冲突"),
        HallucinationType("能力越界"),
    ]


def test_classification_enforces_union_hallucination_and_primary_type() -> None:
    labelled = ClaimJudgement(
        claim=_claim(),
        verdict="unsupported",
        labels=[HallucinationType("无依据编造")],
        severity=Severity("中"),
        evidence=None,
        core_relevance="high",
        reason="reason",
    )
    valid = {
        "is_hallucination": True,
        "labels": [HallucinationType("无依据编造")],
        "primary_type": HallucinationType("无依据编造"),
        "severity": Severity("中"),
        "review_required": False,
        "claims": [labelled],
        "omissions": [],
        "summary": "summary",
    }
    ClassificationResult.model_validate(valid)

    updates: tuple[dict[str, Any], ...] = (
        {"is_hallucination": False},
        {"labels": []},
        {"primary_type": HallucinationType("知识冲突")},
        {"severity": None},
    )
    for update in updates:
        with pytest.raises(ValidationError, match="classification"):
            ClassificationResult.model_validate({**valid, **update})


def test_classification_review_rules_cover_supported_unverifiable_and_empty() -> None:
    normal = ClassificationResult(
        is_hallucination=False,
        labels=[],
        primary_type=None,
        severity=None,
        review_required=False,
        claims=[_supported()],
        omissions=[],
        summary="normal",
    )
    assert normal.review_required is False

    empty = normal.model_dump()
    empty.update(claims=[], review_required=True)
    ClassificationResult.model_validate(empty)
    with pytest.raises(ValidationError, match="review_required"):
        ClassificationResult.model_validate({**empty, "review_required": False})

    unverifiable = _supported().model_copy(update={"verdict": "unverifiable", "evidence": None})
    with pytest.raises(ValidationError, match="review_required"):
        ClassificationResult.model_validate(
            {**empty, "claims": [unverifiable], "review_required": False}
        )


def test_omission_forces_hallucination_and_its_label_into_the_union() -> None:
    omission = OmissionFinding(
        omission_id="h01-o01",
        missing_fact="需要保留包装",
        label="关键遗漏或歪曲",
        severity=Severity("高"),
        evidence=_evidence(),
        core_relevance="high",
        reason="遗漏重要条件",
    )

    result = ClassificationResult(
        is_hallucination=True,
        labels=[HallucinationType("关键遗漏或歪曲")],
        primary_type=HallucinationType("关键遗漏或歪曲"),
        severity=Severity("高"),
        review_required=False,
        claims=[],
        omissions=[omission],
        summary="有关键遗漏",
    )
    assert result.labels == [HallucinationType("关键遗漏或歪曲")]
