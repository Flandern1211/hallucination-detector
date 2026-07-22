from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import re
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from src.domain.enums import HallucinationType, Severity
from src.domain.hashing import content_hash


_ILLEGAL_C0 = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_STABLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_LABEL_ORDER = {label: index for index, label in enumerate(HallucinationType)}

ShortText = Annotated[str, Field(max_length=2_000)]
ClaimText = Annotated[str, Field(max_length=5_000)]
SummaryText = Annotated[str, Field(max_length=4_000)]
ReplyText = Annotated[str, Field(max_length=10_000)]
KnowledgeText = Annotated[str, Field(max_length=50_000)]
RiskText = Annotated[str, Field(max_length=1_000)]


def _reject_illegal_c0(value: Any) -> None:
    if isinstance(value, str):
        if _ILLEGAL_C0.search(value):
            raise ValueError("strings must not contain NUL or illegal C0 control characters")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_illegal_c0(key)
            _reject_illegal_c0(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            _reject_illegal_c0(item)


def normalize_stable_id(value: str) -> str:
    normalized = value.strip()
    if _STABLE_ID.fullmatch(normalized) is None:
        raise ValueError("id must match [A-Za-z0-9][A-Za-z0-9._-]{0,127}")
    return normalized


def _validate_generated_id(value: str) -> str:
    if value != value.strip() or _STABLE_ID.fullmatch(value) is None:
        raise ValueError("generated id must use the stable id format without surrounding spaces")
    return value


def _require_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


def _ordered_unique_labels(labels: list[HallucinationType]) -> list[HallucinationType]:
    return sorted(set(labels), key=_LABEL_ORDER.__getitem__)


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone")
    return value.astimezone(UTC)


def _utc_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @model_validator(mode="after")
    def reject_illegal_control_characters(self) -> StrictModel:
        _reject_illegal_c0(self.model_dump())
        return self


class ReplyRecord(StrictModel):
    id: str
    user_question: ReplyText
    system_reply: ReplyText
    knowledge_base: KnowledgeText

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("id must be a string")
        return normalize_stable_id(value)

    @model_validator(mode="after")
    def require_question_and_reply(self) -> ReplyRecord:
        _require_non_blank(self.user_question, "user_question")
        _require_non_blank(self.system_reply, "system_reply")
        return self


class Claim(StrictModel):
    claim_id: str
    text: ClaimText
    source_quote: ReplyText
    source_start_offset: Annotated[int, Field(ge=0)]
    source_end_offset: Annotated[int, Field(ge=0)]
    kind: Literal["fact", "policy", "capability", "advice"]

    @field_validator("claim_id")
    @classmethod
    def validate_claim_id(cls, value: str) -> str:
        return _validate_generated_id(value)

    @model_validator(mode="after")
    def validate_offset_order(self) -> Claim:
        if self.source_start_offset >= self.source_end_offset:
            raise ValueError("source_end_offset must be greater than source_start_offset")
        return self


class EvidenceReference(StrictModel):
    quote: KnowledgeText
    start_offset: Annotated[int, Field(ge=0)]
    end_offset: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_offset_order(self) -> EvidenceReference:
        if self.start_offset >= self.end_offset:
            raise ValueError("end_offset must be greater than start_offset")
        return self


def validate_claim_quote(claim: Claim, system_reply: str) -> None:
    if claim.source_end_offset > len(system_reply):
        raise ValueError("source_quote offsets exceed system_reply")
    if system_reply[claim.source_start_offset : claim.source_end_offset] != claim.source_quote:
        raise ValueError("source_quote does not match the system_reply slice")


def validate_evidence_quote(evidence: EvidenceReference, knowledge_base: str) -> None:
    if evidence.end_offset > len(knowledge_base):
        raise ValueError("quote offsets exceed knowledge_base")
    if knowledge_base[evidence.start_offset : evidence.end_offset] != evidence.quote:
        raise ValueError("quote does not match the knowledge_base slice")


class ClaimJudgement(StrictModel):
    claim: Claim
    verdict: Literal["supported", "contradicted", "unsupported", "unverifiable"]
    labels: list[HallucinationType]
    severity: Severity | None
    evidence: EvidenceReference | None
    core_relevance: Literal["high", "medium", "low"]
    reason: ShortText

    @field_validator("labels")
    @classmethod
    def normalize_labels(cls, value: list[HallucinationType]) -> list[HallucinationType]:
        return _ordered_unique_labels(value)

    @model_validator(mode="after")
    def validate_verdict_fields(self) -> ClaimJudgement:
        if self.verdict == "supported":
            valid = not self.labels and self.severity is None and self.evidence is not None
        elif self.verdict == "contradicted":
            valid = bool(self.labels) and self.severity is not None and self.evidence is not None
        elif self.verdict == "unsupported":
            valid = bool(self.labels) and self.severity is not None and self.evidence is None
        else:
            valid = not self.labels and self.severity is None and self.evidence is None
        if not valid:
            raise ValueError(f"fields are inconsistent with verdict {self.verdict!r}")
        return self


class OmissionFinding(StrictModel):
    omission_id: str
    missing_fact: Annotated[str, Field(max_length=2_000)]
    label: Literal["关键遗漏或歪曲"]
    severity: Severity
    evidence: EvidenceReference
    core_relevance: Literal["high", "medium", "low"]
    reason: ShortText

    @field_validator("omission_id")
    @classmethod
    def validate_omission_id(cls, value: str) -> str:
        return _validate_generated_id(value)


class ClassificationResult(StrictModel):
    is_hallucination: bool
    labels: list[HallucinationType]
    primary_type: HallucinationType | None
    severity: Severity | None
    review_required: bool
    claims: Annotated[list[ClaimJudgement], Field(max_length=10)]
    omissions: list[OmissionFinding]
    summary: SummaryText

    @field_validator("labels")
    @classmethod
    def normalize_labels(cls, value: list[HallucinationType]) -> list[HallucinationType]:
        return _ordered_unique_labels(value)

    @model_validator(mode="after")
    def validate_classification(self) -> ClassificationResult:
        component_labels = [label for judgement in self.claims for label in judgement.labels]
        component_labels.extend(
            HallucinationType.critical_omission_or_distortion for _ in self.omissions
        )
        expected_labels = _ordered_unique_labels(component_labels)
        expected_hallucination = bool(expected_labels)
        if self.labels != expected_labels or self.is_hallucination != expected_hallucination:
            raise ValueError(
                "classification must match the stable union of claim and omission labels"
            )

        if expected_hallucination:
            if self.primary_type not in self.labels or self.severity is None:
                raise ValueError(
                    "classification primary_type and severity are required for hallucinations"
                )
        elif self.primary_type is not None or self.severity is not None:
            raise ValueError("classification primary_type and severity must be null when normal")

        review_is_required = not self.claims and not self.omissions
        review_is_required = review_is_required or any(
            judgement.verdict == "unverifiable" for judgement in self.claims
        )
        if review_is_required and not self.review_required:
            raise ValueError("review_required does not match the classification evidence state")
        if not expected_hallucination and not review_is_required and self.review_required:
            raise ValueError("supported-only classifications must not require review")
        return self


PredictionErrorCode: TypeAlias = Literal[
    "timeout",
    "rate_limited",
    "provider_error",
    "invalid_structure",
    "claim_limit_exceeded",
    "context_rejected",
    "request_budget_exhausted",
    "token_budget_exhausted",
    "provider_usage_missing",
    "cancelled",
    "run_deadline_exceeded",
]


class SuccessfulPrediction(StrictModel):
    kind: Literal["success"]
    id: str
    result: ClassificationResult
    engine: Literal["llm"]
    model_name: str
    detector_version: str
    config_hash: str
    attempt_count: Annotated[int, Field(ge=1)]

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("id must be a string")
        return normalize_stable_id(value)


class FailedPrediction(StrictModel):
    kind: Literal["failure"]
    id: str
    error_code: PredictionErrorCode
    error_summary: str
    attempt_count: Annotated[int, Field(ge=0)]
    model_name: str | None

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("id must be a string")
        return normalize_stable_id(value)


PredictionResult: TypeAlias = Annotated[
    SuccessfulPrediction | FailedPrediction, Field(discriminator="kind")
]


class ProviderUsage(StrictModel):
    prompt_tokens: Annotated[int, Field(ge=0)]
    completion_tokens: Annotated[int, Field(ge=0)]
    total_tokens: Annotated[int, Field(ge=0)]


class BatchDetectionResult(StrictModel):
    schema_version: Literal["1.0"]
    results: Annotated[list[PredictionResult], Field(min_length=1, max_length=20)]
    input_hash: str
    detector_config_hash: str
    network_attempt_count: Annotated[int, Field(ge=0)]
    provider_usage: ProviderUsage
    stopped_reason: str | None

    @model_validator(mode="after")
    def validate_network_attempt_count(self) -> BatchDetectionResult:
        expected = sum(result.attempt_count for result in self.results)
        if self.network_attempt_count != expected:
            raise ValueError("network_attempt_count must equal the sum of record attempt_count")
        return self


class DetectionRunConfig(StrictModel):
    detector_version: Literal["baseline-v1"]
    manual_review_enabled: bool = False
    external_processing_acknowledged: Literal[True]


class HumanReviewRevision(StrictModel):
    schema_version: Literal["1.0"]
    review_id: str
    run_id: str
    record_id: str
    status: Literal["confirmed_correct", "corrected"]
    source_prediction_hash: str
    reviewed_result: ClassificationResult
    changed_fields: list[str]
    revision_number: Annotated[int, Field(ge=1)]
    save_request_id: str
    created_at_utc: datetime
    previous_event_hash: str | None
    event_hash: str

    @field_validator("record_id", mode="before")
    @classmethod
    def normalize_record_id(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("record_id must be a string")
        return normalize_stable_id(value)

    @field_validator("created_at_utc")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return _utc_datetime(value)

    @field_serializer("created_at_utc", when_used="json")
    def serialize_created_at(self, value: datetime) -> str:
        return _utc_z(value)

    @model_validator(mode="after")
    def validate_event_chain(self) -> HumanReviewRevision:
        if self.revision_number == 1 and self.previous_event_hash is not None:
            raise ValueError("previous_event_hash must be null for revision 1")
        if self.revision_number > 1 and self.previous_event_hash is None:
            raise ValueError("previous_event_hash is required after revision 1")
        expected = content_hash(self, frozenset({"event_hash"}))
        if self.event_hash != expected:
            raise ValueError("event_hash does not match canonical event content")
        return self


class GroundTruthRecord(StrictModel):
    id: str
    is_hallucination: bool
    hallucination_type: str | None
    detail: ReplyText
    severity: Severity | None = None

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("id must be a string")
        return normalize_stable_id(value)

    @model_validator(mode="after")
    def validate_ground_truth(self) -> GroundTruthRecord:
        if self.is_hallucination:
            if self.hallucination_type is None or not self.hallucination_type.strip():
                raise ValueError("positive ground truth requires a non-empty hallucination_type")
            if not self.detail.strip():
                raise ValueError("positive ground truth requires non-empty detail")
        elif self.hallucination_type is not None or self.severity is not None:
            raise ValueError("normal ground truth requires null hallucination_type and severity")
        return self


class RiskReference(StrictModel):
    schema_version: Literal["1.0"]
    version: str
    source: Literal["uploaded_ground_truth", "frozen_benchmark_map"]
    ground_truth_hash: str
    risk_rule_version: str
    severity_by_positive_id: dict[str, Severity]
    content_hash: str

    @field_validator("severity_by_positive_id")
    @classmethod
    def validate_positive_ids(cls, value: dict[str, Severity]) -> dict[str, Severity]:
        for record_id in value:
            if normalize_stable_id(record_id) != record_id:
                raise ValueError("severity_by_positive_id keys must be normalized stable ids")
        return value

    @model_validator(mode="after")
    def validate_content_hash(self) -> RiskReference:
        expected = content_hash(self, frozenset({"content_hash"}))
        if self.content_hash != expected:
            raise ValueError("content_hash does not match canonical risk reference content")
        return self


class BaselineDetectorConfig(StrictModel):
    schema_version: Literal["1.0"]
    version: Literal["baseline-v1"]
    claim_extraction_system_prompt: str
    evidence_judgement_system_prompt: str
    completeness_check_system_prompt: str
    error_analysis_system_prompt: str
    suggestion_system_prompt: str
    hallucination_type_definitions: dict[HallucinationType, str]
    severity_definitions: dict[Severity, str]
    max_claims: Literal[10]
    temperature: Literal[0]
    provider_response_schema_version: Literal["1.0"]

    @model_validator(mode="after")
    def validate_definition_keys(self) -> BaselineDetectorConfig:
        if set(self.hallucination_type_definitions) != set(HallucinationType):
            raise ValueError("hallucination_type_definitions must contain exactly all five labels")
        if set(self.severity_definitions) != set(Severity):
            raise ValueError("severity_definitions must contain exactly all three severities")
        return self


ErrorReason: TypeAlias = Literal[
    "claim_not_extracted",
    "evidence_misread",
    "unsupported_boundary_too_loose",
    "unsupported_boundary_too_strict",
    "capability_pattern_missed",
    "partial_support_misclassified",
    "critical_omission_boundary",
    "non_factual_expression_false_positive",
    "semantic_equivalence_or_negation_error",
]

ErrorAnalysisCode: TypeAlias = Literal[
    "timeout",
    "rate_limited",
    "provider_error",
    "invalid_structure",
    "request_budget_exhausted",
    "token_budget_exhausted",
    "provider_usage_missing",
    "cancelled",
    "run_deadline_exceeded",
]


class SuccessfulErrorAnalysis(StrictModel):
    kind: Literal["success"]
    case_ref: str
    error_kind: Literal["false_negative", "false_positive"]
    primary_reason: ErrorReason
    secondary_reasons: list[ErrorReason]
    evidence: SummaryText
    proposed_improvement: SummaryText

    @field_validator("secondary_reasons")
    @classmethod
    def deduplicate_secondary_reasons(cls, value: list[ErrorReason]) -> list[ErrorReason]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_error_analysis(self) -> SuccessfulErrorAnalysis:
        _require_non_blank(self.evidence, "evidence")
        _require_non_blank(self.proposed_improvement, "proposed_improvement")
        if self.primary_reason in self.secondary_reasons:
            raise ValueError("secondary_reasons must not repeat primary_reason")
        return self


class FailedErrorAnalysis(StrictModel):
    kind: Literal["failure"]
    case_ref: str
    error_code: ErrorAnalysisCode
    error_summary: str


ErrorAnalysis: TypeAlias = Annotated[
    SuccessfulErrorAnalysis | FailedErrorAnalysis, Field(discriminator="kind")
]


class ExperimentalSuggestion(StrictModel):
    suggestion_id: str
    category: Literal["prompt_principle", "label_boundary", "generalized_example"]
    target_stage: Literal["claim_extraction", "evidence_judgement", "completeness_check"]
    rationale: SummaryText
    proposed_change: SummaryText
    known_risks: Annotated[list[RiskText], Field(min_length=1, max_length=10)]

    @model_validator(mode="after")
    def require_suggestion_content(self) -> ExperimentalSuggestion:
        _require_non_blank(self.rationale, "rationale")
        _require_non_blank(self.proposed_change, "proposed_change")
        for risk in self.known_risks:
            _require_non_blank(risk, "known_risks item")
        return self


class SuggestionReport(StrictModel):
    schema_version: Literal["1.0"]
    run_id: str
    label_source: Literal["official_ground_truth", "human_revision"]
    input_hash: str
    prediction_hash: str
    detector_version: Literal["baseline-v1"]
    detector_config_hash: str
    model_name: str
    generated_at_utc: datetime
    coverage: Annotated[float, Field(ge=0.0, le=1.0)]
    warning: Literal["小样本实验性建议，不代表效果提升"]
    analyses: list[SuccessfulErrorAnalysis]
    suggestions: Annotated[list[ExperimentalSuggestion], Field(max_length=20)]

    @field_validator("generated_at_utc")
    @classmethod
    def normalize_generated_at(cls, value: datetime) -> datetime:
        return _utc_datetime(value)

    @field_serializer("generated_at_utc", when_used="json")
    def serialize_generated_at(self, value: datetime) -> str:
        return _utc_z(value)
