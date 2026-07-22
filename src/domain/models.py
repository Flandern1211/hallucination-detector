from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import re
from types import MappingProxyType
from typing import Annotated, Any, Literal, TypeAlias, TypeVar, cast

from pydantic import (
    BaseModel,
    AfterValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    field_serializer,
    field_validator,
    model_validator,
)

from src.domain.enums import HallucinationType, Severity
from src.domain.hashing import content_hash


_ILLEGAL_C0 = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_STABLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_LABEL_ORDER = {label: index for index, label in enumerate(HallucinationType)}
_PROMPT_TEMPLATE = re.compile(r"\{\{|\}\}|\{%|%\}|<%|%>|\$\{|\{[A-Za-z_][^{}\r\n]*\}")
_PROMPT_URL = re.compile(r"(?i)(?:https?|ftp)://|\bwww\.")
_PROMPT_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|(?:^|\s)(?:\.\.[\\/]|/[A-Za-z0-9._-]))")
_PROMPT_EXECUTABLE = re.compile(
    r"(?i)```|<script\b|#!|\$\(|&&|\|\||"
    r"(?:^|[\r\n])\s*(?:powershell|cmd(?:\.exe)?|bash|sh|python)\s+"
    r"(?:-|/|[A-Za-z0-9_.]+\.py\b)"
)

T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")


class _ImmutableSequence(tuple[Any, ...]):
    def __eq__(self, other: object) -> bool:
        if isinstance(other, (list, tuple)):
            return tuple(self) == tuple(other)
        return False

    __hash__ = tuple.__hash__


def _freeze_list(value: list[T]) -> list[T]:
    return cast(list[T], _ImmutableSequence(value))


def _freeze_mapping(value: Mapping[K, V]) -> Mapping[K, V]:
    return MappingProxyType(dict(value))


FrozenSequence: TypeAlias = Annotated[
    list[T],
    AfterValidator(_freeze_list),
    PlainSerializer(lambda value: list(value), return_type=list),
]
FrozenMapping: TypeAlias = Annotated[
    Mapping[K, V],
    AfterValidator(_freeze_mapping),
    PlainSerializer(lambda value: dict(value), return_type=dict),
]

ShortText = Annotated[str, Field(max_length=2_000)]
ClaimText = Annotated[str, Field(max_length=5_000)]
SummaryText = Annotated[str, Field(max_length=4_000)]
ReplyText = Annotated[str, Field(max_length=10_000)]
KnowledgeText = Annotated[str, Field(max_length=50_000)]
RiskText = Annotated[str, Field(max_length=1_000)]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


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


def _validate_system_prompt(value: str) -> str:
    if not value.strip():
        raise ValueError("prompt must not be blank")
    if "UNTRUSTED_DATA" not in value and "数据而非指令" not in value:
        raise ValueError("prompt must define an untrusted-data boundary")
    if _PROMPT_TEMPLATE.search(value):
        raise ValueError("prompt must not contain template or runtime placeholders")
    if _PROMPT_URL.search(value):
        raise ValueError("prompt must not contain a URL")
    if _PROMPT_PATH.search(value):
        raise ValueError("prompt must not contain a file path")
    if _PROMPT_EXECUTABLE.search(value):
        raise ValueError("prompt must not contain executable code or command syntax")
    return value


def _ordered_unique_labels(
    labels: Sequence[HallucinationType],
) -> list[HallucinationType]:
    return cast(
        list[HallucinationType],
        _ImmutableSequence(sorted(set(labels), key=_LABEL_ORDER.__getitem__)),
    )


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone")
    return value.astimezone(UTC)


def _utc_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="never"
    )

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
    labels: FrozenSequence[HallucinationType]
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
    labels: FrozenSequence[HallucinationType]
    primary_type: HallucinationType | None
    severity: Severity | None
    review_required: bool
    claims: Annotated[FrozenSequence[ClaimJudgement], Field(max_length=10)]
    omissions: FrozenSequence[OmissionFinding]
    summary: SummaryText

    @field_validator("labels")
    @classmethod
    def normalize_labels(cls, value: list[HallucinationType]) -> list[HallucinationType]:
        return _ordered_unique_labels(value)

    @model_validator(mode="after")
    def validate_classification(self) -> ClassificationResult:
        claim_ids = [judgement.claim.claim_id for judgement in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("claim_id values must be unique within a classification")
        omission_ids = [omission.omission_id for omission in self.omissions]
        if len(omission_ids) != len(set(omission_ids)):
            raise ValueError("omission_id values must be unique within a classification")

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

_ZERO_ATTEMPT_ERROR_CODES = frozenset(
    {
        "request_budget_exhausted",
        "token_budget_exhausted",
        "cancelled",
        "run_deadline_exceeded",
    }
)


class SuccessfulPrediction(StrictModel):
    kind: Literal["success"]
    id: str
    result: ClassificationResult
    engine: Literal["llm"]
    model_name: str
    detector_version: str
    config_hash: Sha256Hex
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

    @model_validator(mode="after")
    def validate_attempt_count_for_error(self) -> FailedPrediction:
        if self.attempt_count == 0 and self.error_code not in _ZERO_ATTEMPT_ERROR_CODES:
            raise ValueError(f"attempt_count must be at least 1 for {self.error_code!r}")
        return self


PredictionResult: TypeAlias = Annotated[
    SuccessfulPrediction | FailedPrediction, Field(discriminator="kind")
]


class ProviderUsage(StrictModel):
    prompt_tokens: Annotated[int, Field(ge=0)]
    completion_tokens: Annotated[int, Field(ge=0)]
    total_tokens: Annotated[int, Field(ge=0)]


class BatchDetectionResult(StrictModel):
    schema_version: Literal["1.0"]
    results: Annotated[FrozenSequence[PredictionResult], Field(min_length=1, max_length=20)]
    input_hash: Sha256Hex
    detector_config_hash: Sha256Hex
    network_attempt_count: Annotated[int, Field(ge=0)]
    provider_usage: ProviderUsage
    stopped_reason: str | None

    @model_validator(mode="after")
    def validate_network_attempt_count(self) -> BatchDetectionResult:
        expected = sum(result.attempt_count for result in self.results)
        if self.network_attempt_count != expected:
            raise ValueError("network_attempt_count must equal the sum of record attempt_count")
        return self


class ProgressEvent(StrictModel):
    record_id: str
    completed_count: Annotated[int, Field(ge=1)]
    total_count: Annotated[int, Field(ge=1)]
    outcome: Literal["success", "failure"]

    @field_validator("record_id", mode="before")
    @classmethod
    def normalize_record_id(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("record_id must be a string")
        return normalize_stable_id(value)

    @model_validator(mode="after")
    def validate_progress(self) -> ProgressEvent:
        if self.completed_count > self.total_count:
            raise ValueError("completed_count must not exceed total_count")
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
    source_prediction_hash: Sha256Hex
    reviewed_result: ClassificationResult
    changed_fields: FrozenSequence[str]
    revision_number: Annotated[int, Field(ge=1)]
    save_request_id: str
    created_at_utc: datetime
    previous_event_hash: Sha256Hex | None
    event_hash: Sha256Hex

    @field_validator("reviewed_result", mode="before")
    @classmethod
    def parse_reviewed_result(cls, value: Any) -> ClassificationResult:
        if isinstance(value, ClassificationResult):
            return value
        if isinstance(value, Mapping):
            data = dict(value)
            data["labels"] = [HallucinationType(label) for label in data.get("labels", [])]
            if data.get("primary_type") is not None:
                data["primary_type"] = HallucinationType(data["primary_type"])
            if data.get("severity") is not None:
                data["severity"] = Severity(data["severity"])
            claims = []
            for claim in data.get("claims", []):
                claim_data = dict(claim)
                claim_data["labels"] = [
                    HallucinationType(label) for label in claim_data.get("labels", [])
                ]
                if claim_data.get("severity") is not None:
                    claim_data["severity"] = Severity(claim_data["severity"])
                claims.append(claim_data)
            data["claims"] = claims
            omissions = []
            for omission in data.get("omissions", []):
                omission_data = dict(omission)
                omission_data["severity"] = Severity(omission_data["severity"])
                omissions.append(omission_data)
            data["omissions"] = omissions
            return ClassificationResult.model_validate(data)
        return cast(ClassificationResult, value)

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
    ground_truth_hash: Sha256Hex
    risk_rule_version: str
    severity_by_positive_id: FrozenMapping[str, Severity]
    content_hash: Sha256Hex

    @field_validator("severity_by_positive_id")
    @classmethod
    def validate_positive_ids(cls, value: Mapping[str, Severity]) -> Mapping[str, Severity]:
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
    hallucination_type_definitions: FrozenMapping[HallucinationType, str]
    severity_definitions: FrozenMapping[Severity, str]
    max_claims: Literal[10]
    temperature: Literal[0]
    provider_response_schema_version: Literal["1.0"]

    @field_validator(
        "claim_extraction_system_prompt",
        "evidence_judgement_system_prompt",
        "completeness_check_system_prompt",
        "error_analysis_system_prompt",
        "suggestion_system_prompt",
    )
    @classmethod
    def validate_system_prompt(cls, value: str) -> str:
        return _validate_system_prompt(value)

    @model_validator(mode="after")
    def validate_definition_keys(self) -> BaselineDetectorConfig:
        if set(self.hallucination_type_definitions) != set(HallucinationType):
            raise ValueError("hallucination_type_definitions must contain exactly all five labels")
        if set(self.severity_definitions) != set(Severity):
            raise ValueError("severity_definitions must contain exactly all three severities")
        return self


class ErrorAnalysisInput(StrictModel):
    case_ref: str
    error_kind: Literal["false_negative", "false_positive"]
    user_question: ReplyText
    system_reply: ReplyText
    knowledge_base: KnowledgeText
    prediction: ClassificationResult
    expected_is_hallucination: bool
    expected_labels: FrozenSequence[HallucinationType]

    @field_validator("case_ref")
    @classmethod
    def validate_case_ref(cls, value: str) -> str:
        return _validate_generated_id(value)

    @field_validator("expected_labels")
    @classmethod
    def normalize_expected_labels(cls, value: list[HallucinationType]) -> list[HallucinationType]:
        return _ordered_unique_labels(value)

    @model_validator(mode="after")
    def validate_error_kind(self) -> ErrorAnalysisInput:
        if self.expected_is_hallucination != bool(self.expected_labels):
            raise ValueError("expected labels must match expected_is_hallucination")
        is_false_negative = self.expected_is_hallucination and not self.prediction.is_hallucination
        is_false_positive = not self.expected_is_hallucination and self.prediction.is_hallucination
        if self.error_kind == "false_negative" and not is_false_negative:
            raise ValueError("false_negative input must contain a false-negative prediction")
        if self.error_kind == "false_positive" and not is_false_positive:
            raise ValueError("false_positive input must contain a false-positive prediction")
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
    secondary_reasons: FrozenSequence[ErrorReason]
    evidence: SummaryText
    proposed_improvement: SummaryText

    @field_validator("secondary_reasons")
    @classmethod
    def deduplicate_secondary_reasons(cls, value: list[ErrorReason]) -> list[ErrorReason]:
        return cast(list[ErrorReason], _ImmutableSequence(dict.fromkeys(value)))

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


class ExperimentalSuggestionBody(StrictModel):
    category: Literal["prompt_principle", "label_boundary", "generalized_example"]
    target_stage: Literal["claim_extraction", "evidence_judgement", "completeness_check"]
    rationale: SummaryText
    proposed_change: SummaryText
    known_risks: Annotated[FrozenSequence[RiskText], Field(min_length=1, max_length=10)]

    @model_validator(mode="after")
    def require_suggestion_content(self) -> ExperimentalSuggestionBody:
        _require_non_blank(self.rationale, "rationale")
        _require_non_blank(self.proposed_change, "proposed_change")
        for risk in self.known_risks:
            _require_non_blank(risk, "known_risks item")
        return self


class ExperimentalSuggestion(StrictModel):
    suggestion_id: str
    category: Literal["prompt_principle", "label_boundary", "generalized_example"]
    target_stage: Literal["claim_extraction", "evidence_judgement", "completeness_check"]
    rationale: SummaryText
    proposed_change: SummaryText
    known_risks: Annotated[FrozenSequence[RiskText], Field(min_length=1, max_length=10)]

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
    input_hash: Sha256Hex
    prediction_hash: Sha256Hex
    detector_version: Literal["baseline-v1"]
    detector_config_hash: Sha256Hex
    model_name: str
    generated_at_utc: datetime
    coverage: Annotated[float, Field(ge=0.0, le=1.0)]
    warning: Literal["小样本实验性建议，不代表效果提升"]
    analyses: FrozenSequence[SuccessfulErrorAnalysis]
    suggestions: Annotated[FrozenSequence[ExperimentalSuggestion], Field(max_length=20)]

    @field_validator("generated_at_utc")
    @classmethod
    def normalize_generated_at(cls, value: datetime) -> datetime:
        return _utc_datetime(value)

    @field_serializer("generated_at_utc", when_used="json")
    def serialize_generated_at(self, value: datetime) -> str:
        return _utc_z(value)
