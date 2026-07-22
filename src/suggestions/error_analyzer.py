from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from src.domain.enums import HallucinationType, RunState
from src.domain.hashing import content_hash
from src.domain.models import (
    ErrorAnalysis,
    ErrorAnalysisInput,
    GroundTruthRecord,
    HumanReviewRevision,
    PredictionResult,
    ReplyRecord,
    SuccessfulErrorAnalysis,
    SuccessfulPrediction,
)


class SuggestionRun(Protocol):
    id: str
    state: RunState
    records: Sequence[ReplyRecord]
    predictions: Sequence[PredictionResult]
    input_hash: str
    prediction_hash: str
    detector_config_hash: str


class LabelSourceIneligible(RuntimeError):
    pass


class InvalidErrorAnalysis(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OfficialSource:
    labels: tuple[GroundTruthRecord, ...]
    coverage: float


@dataclass(frozen=True, slots=True)
class HumanRevisionSource:
    revisions: tuple[HumanReviewRevision, ...]
    total_success_count: int
    reviewed_success_count: int


@dataclass(frozen=True, slots=True)
class SuggestionCases:
    label_source: Literal["official_ground_truth", "human_revision"]
    items: tuple[ErrorAnalysisInput, ...]
    record_id_by_case_ref: dict[str, str]

    def provider_payload(self) -> list[dict[str, object]]:
        return [
            {
                "case_ref": item.case_ref,
                "error_kind": item.error_kind,
                "user_question": item.user_question,
                "system_reply": item.system_reply,
                "knowledge_base": item.knowledge_base,
                "prediction": item.prediction.model_dump(mode="json"),
                "expected_is_hallucination": item.expected_is_hallucination,
                "expected_labels": [label.value for label in item.expected_labels],
            }
            for item in self.items
        ]


def build_cases(
    run: SuggestionRun, label_source: OfficialSource | HumanRevisionSource
) -> SuggestionCases:
    if run.state is not RunState.frozen:
        raise LabelSourceIneligible("run must be frozen")
    labels, source_name = _labels(run, label_source)
    success_predictions = [p for p in run.predictions if isinstance(p, SuccessfulPrediction)]
    if set(labels) != {prediction.id for prediction in success_predictions}:
        raise LabelSourceIneligible("label ids must match successful prediction ids")

    records = {record.id: record for record in run.records}
    items: list[ErrorAnalysisInput] = []
    mapping: dict[str, str] = {}
    for prediction in success_predictions:
        expected = labels[prediction.id]
        if expected.is_hallucination == prediction.result.is_hallucination:
            continue
        case_ref = f"case-{len(items) + 1:03d}"
        expected_labels = _expected_labels(expected)
        item = ErrorAnalysisInput(
            case_ref=case_ref,
            error_kind="false_negative" if expected.is_hallucination else "false_positive",
            user_question=records[prediction.id].user_question,
            system_reply=records[prediction.id].system_reply,
            knowledge_base=records[prediction.id].knowledge_base,
            prediction=prediction.result,
            expected_is_hallucination=expected.is_hallucination,
            expected_labels=expected_labels,
        )
        items.append(item)
        mapping[case_ref] = prediction.id
    return SuggestionCases(source_name, tuple(items), mapping)


def validate_analyses(
    expected_cases: tuple[ErrorAnalysisInput, ...] | list[ErrorAnalysisInput],
    analyses: list[ErrorAnalysis] | tuple[object, ...],
) -> tuple[SuccessfulErrorAnalysis, ...]:
    if len(expected_cases) != len(analyses):
        raise InvalidErrorAnalysis("analysis set does not match cases")
    valid: list[SuccessfulErrorAnalysis] = []
    for expected, analysis in zip(expected_cases, analyses, strict=True):
        if not isinstance(analysis, SuccessfulErrorAnalysis):
            raise InvalidErrorAnalysis("failed analysis")
        if analysis.case_ref != expected.case_ref or analysis.error_kind != expected.error_kind:
            raise InvalidErrorAnalysis("analysis order or kind mismatch")
        valid.append(analysis)
    return tuple(valid)


def _labels(
    run: SuggestionRun, source: OfficialSource | HumanRevisionSource
) -> tuple[dict[str, GroundTruthRecord], Literal["official_ground_truth", "human_revision"]]:
    if isinstance(source, OfficialSource):
        if source.coverage != 1.0:
            raise LabelSourceIneligible("suggestions require 100% official coverage")
        return {label.id: label for label in source.labels}, "official_ground_truth"
    if source.reviewed_success_count != source.total_success_count:
        raise LabelSourceIneligible("suggestions require 100% human review coverage")
    predictions = {prediction.id: prediction for prediction in run.predictions}
    labels = {}
    for revision in source.revisions:
        prediction = predictions.get(revision.record_id)
        if not isinstance(prediction, SuccessfulPrediction):
            raise LabelSourceIneligible("revision target unavailable")
        if revision.source_prediction_hash != content_hash(prediction):
            raise LabelSourceIneligible("stale human revision")
        labels[revision.record_id] = GroundTruthRecord(
            id=revision.record_id,
            is_hallucination=revision.reviewed_result.is_hallucination,
            hallucination_type=(
                revision.reviewed_result.primary_type.value
                if revision.reviewed_result.primary_type is not None
                else None
            ),
            detail=revision.reviewed_result.summary
            if revision.reviewed_result.is_hallucination
            else "",
            severity=revision.reviewed_result.severity,
        )
    return labels, "human_revision"


def _expected_labels(record: GroundTruthRecord) -> list[HallucinationType]:
    if not record.is_hallucination or record.hallucination_type is None:
        return []
    return [HallucinationType(record.hallucination_type)]
