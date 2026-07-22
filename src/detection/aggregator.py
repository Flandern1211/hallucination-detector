from dataclasses import dataclass

from src.domain.enums import HallucinationType, Severity
from src.domain.models import ClassificationResult, ClaimJudgement, OmissionFinding


_TYPE_ORDER = {label: index for index, label in enumerate(HallucinationType)}
_SEVERITY_RANK = {Severity.high: 3, Severity.medium: 2, Severity.low: 1}
_EVIDENCE_RANK = {"contradicted": 3, "omission": 2, "unsupported": 1}
_RELEVANCE_RANK = {"high": 3, "medium": 2, "low": 1}


@dataclass(frozen=True)
class _Finding:
    label: HallucinationType
    severity: Severity
    evidence_kind: str
    relevance: str
    item_index: int


def _findings(judgements: list[ClaimJudgement], omissions: list[OmissionFinding]) -> list[_Finding]:
    values: list[_Finding] = []
    for item_index, judgement in enumerate(judgements):
        if judgement.severity is None:
            continue
        for label in judgement.labels:
            values.append(
                _Finding(
                    label=label,
                    severity=judgement.severity,
                    evidence_kind=judgement.verdict,
                    relevance=judgement.core_relevance,
                    item_index=item_index,
                )
            )
    offset = len(judgements)
    for omission_index, omission in enumerate(omissions):
        values.append(
            _Finding(
                label=HallucinationType.critical_omission_or_distortion,
                severity=omission.severity,
                evidence_kind="omission",
                relevance=omission.core_relevance,
                item_index=offset + omission_index,
            )
        )
    return values


def _priority(finding: _Finding) -> tuple[int, int, int, int, int]:
    return (
        _SEVERITY_RANK[finding.severity],
        _EVIDENCE_RANK[finding.evidence_kind],
        _RELEVANCE_RANK[finding.relevance],
        -finding.item_index,
        -_TYPE_ORDER[finding.label],
    )


def aggregate(
    judgements: list[ClaimJudgement], omissions: list[OmissionFinding], summary: str
) -> ClassificationResult:
    findings = _findings(judgements, omissions)
    if not findings:
        return ClassificationResult(
            is_hallucination=False,
            labels=[],
            primary_type=None,
            severity=None,
            review_required=not judgements
            or any(item.verdict == "unverifiable" for item in judgements),
            claims=judgements,
            omissions=omissions,
            summary=summary,
        )

    labels = sorted({finding.label for finding in findings}, key=_TYPE_ORDER.__getitem__)
    winner = max(findings, key=_priority)
    severity = max((finding.severity for finding in findings), key=_SEVERITY_RANK.__getitem__)
    return ClassificationResult(
        is_hallucination=True,
        labels=labels,
        primary_type=winner.label,
        severity=severity,
        review_required=any(item.verdict == "unverifiable" for item in judgements),
        claims=judgements,
        omissions=omissions,
        summary=summary,
    )
