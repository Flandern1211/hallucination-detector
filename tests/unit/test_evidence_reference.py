from typing import Any, cast

import pytest
from pydantic import ValidationError

from src.domain.enums import Severity
from src.domain.hashing import content_hash
from src.domain.models import (
    EvidenceReference,
    GroundTruthRecord,
    RiskReference,
    validate_evidence_quote,
)


def test_evidence_reference_uses_unicode_code_point_offsets() -> None:
    knowledge_base = "🙂七天内可退货"
    evidence = EvidenceReference(quote="七天", start_offset=1, end_offset=3)

    validate_evidence_quote(evidence, knowledge_base)
    with pytest.raises(ValueError, match="quote"):
        validate_evidence_quote(evidence.model_copy(update={"start_offset": 0}), knowledge_base)


@pytest.mark.parametrize(("start", "end"), [(-1, 1), (1, 1), (2, 1)])
def test_evidence_reference_rejects_invalid_offset_ranges(start: int, end: int) -> None:
    with pytest.raises(ValidationError, match="offset"):
        EvidenceReference(quote="x", start_offset=start, end_offset=end)


def test_ground_truth_normalizes_id_and_enforces_label_invariants() -> None:
    normal = GroundTruthRecord(
        id=" h01 ", is_hallucination=False, hallucination_type=None, detail="正常"
    )
    assert normal.id == "h01"
    assert normal.severity is None

    GroundTruthRecord(
        id="h02",
        is_hallucination=True,
        hallucination_type="外部未知类型",
        detail="人工说明",
        severity=None,
    )
    with pytest.raises(ValidationError, match="ground truth"):
        GroundTruthRecord(
            id="h03",
            is_hallucination=False,
            hallucination_type="知识冲突",
            detail="normal",
            severity=None,
        )
    with pytest.raises(ValidationError, match="ground truth"):
        GroundTruthRecord(
            id="h04", is_hallucination=True, hallucination_type=" ", detail=" ", severity=None
        )


def test_risk_reference_hash_excludes_its_own_hash_field() -> None:
    raw = {
        "schema_version": "1.0",
        "version": "risk-v1",
        "source": "uploaded_ground_truth",
        "ground_truth_hash": "a" * 64,
        "risk_rule_version": "risk-rule-v1",
        "severity_by_positive_id": {"h01": "高"},
    }
    expected_hash = content_hash(raw)
    reference = RiskReference.model_validate(
        {
            **raw,
            "severity_by_positive_id": {"h01": Severity("高")},
            "content_hash": expected_hash,
        }
    )

    assert reference.content_hash == expected_hash
    with pytest.raises(ValidationError, match="content_hash"):
        RiskReference.model_validate_json(
            __import__("json").dumps(
                {**reference.model_dump(mode="json"), "content_hash": "0" * 64},
                ensure_ascii=False,
            )
        )

    assert isinstance(reference.model_dump(mode="json")["severity_by_positive_id"], dict)
    with pytest.raises(TypeError):
        cast(Any, reference.severity_by_positive_id)["h02"] = Severity("中")
