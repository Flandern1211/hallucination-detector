from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from src.detection.aggregator import aggregate
from src.domain.enums import RunState
from src.domain.hashing import content_hash, utc_now
from src.domain.models import (
    ClassificationResult,
    HumanReviewRevision,
    SuccessfulPrediction,
    validate_claim_quote,
    validate_evidence_quote,
)
from src.infrastructure.artifact_store import ArtifactStore
from src.infrastructure.run_registry import RunRecord, RunRegistry
from src.reporting.exporter import export_feedback
from src.review.diff import model_equal
from src.review.revision_store import RevisionStore
from src.suggestions.error_analyzer import HumanRevisionSource


class ReviewDisabled(RuntimeError):
    pass


class ReviewTargetUnavailable(RuntimeError):
    pass


class SourcePredictionConflict(RuntimeError):
    pass


class ConfirmedResultMismatch(RuntimeError):
    pass


class ReviewSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: Literal["confirmed_correct", "corrected"]
    save_request_id: str
    source_prediction_hash: str
    reviewed_result: ClassificationResult


@dataclass(frozen=True, slots=True)
class ReviewSnapshot:
    run_id: str
    reviewed_success_count: int
    total_success_count: int
    unreviewed_ids: list[str]
    current_revisions: list[HumanReviewRevision]


class ReviewService:
    def __init__(
        self,
        registry: RunRegistry,
        revisions: RevisionStore,
        *,
        uuid_factory: Callable[[], object] = uuid4,
        clock: Callable[[], datetime] = utc_now,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self._registry = registry
        self._revisions = revisions
        self._uuid_factory = uuid_factory
        self._clock = clock
        self._artifact_store = artifact_store

    def save(self, run_id: str, record_id: str, request: ReviewSaveRequest) -> HumanReviewRevision:
        run = self._registry.get(run_id)
        if run.state is not RunState.frozen:
            raise ReviewTargetUnavailable(record_id)
        if not run.config.manual_review_enabled:
            raise ReviewDisabled(run_id)
        prediction = self._success_prediction(run, record_id)
        if request.source_prediction_hash != content_hash(prediction):
            raise SourcePredictionConflict(record_id)
        if request.status == "confirmed_correct" and not model_equal(
            request.reviewed_result, prediction.result
        ):
            raise ConfirmedResultMismatch(record_id)
        reviewed_result = self._validate_result(run, record_id, request.reviewed_result)
        revision = self._revisions.append(
            run_id=run_id,
            record_id=record_id,
            prediction=prediction,
            status=request.status,
            save_request_id=request.save_request_id,
            reviewed_result=reviewed_result,
            review_id_factory=lambda: str(self._uuid_factory()),
            clock=self._clock,
        )
        self._persist_feedback(run_id)
        return revision

    def restore_original(
        self,
        run_id: str,
        record_id: str,
        save_request_id: str,
        source_prediction_hash: str,
    ) -> HumanReviewRevision:
        run = self._registry.get(run_id)
        prediction = self._success_prediction(run, record_id)
        return self.save(
            run_id,
            record_id,
            ReviewSaveRequest(
                status="corrected",
                save_request_id=save_request_id,
                source_prediction_hash=source_prediction_hash,
                reviewed_result=prediction.result,
            ),
        )

    def review_snapshot(self, run_id: str) -> ReviewSnapshot:
        run = self._registry.get(run_id)
        success_ids = [
            item.id for item in run.predictions if isinstance(item, SuccessfulPrediction)
        ]
        latest = self._revisions.latest_for_run(run_id)
        by_record = {item.record_id: item for item in latest}
        reviewed = set(by_record)
        return ReviewSnapshot(
            run_id=run_id,
            reviewed_success_count=len(reviewed),
            total_success_count=len(success_ids),
            unreviewed_ids=[record_id for record_id in success_ids if record_id not in reviewed],
            current_revisions=[
                by_record[record_id] for record_id in success_ids if record_id in by_record
            ],
        )

    def human_source(self, run_id: str) -> HumanRevisionSource:
        snapshot = self.review_snapshot(run_id)
        return HumanRevisionSource(
            revisions=tuple(snapshot.current_revisions),
            total_success_count=snapshot.total_success_count,
            reviewed_success_count=snapshot.reviewed_success_count,
        )

    def _persist_feedback(self, run_id: str) -> None:
        if self._artifact_store is None:
            return
        snapshot = self.review_snapshot(run_id)
        self._artifact_store.write_json(
            run_id,
            "feedback.json",
            export_feedback(
                {
                    "run_id": snapshot.run_id,
                    "reviewed_success_count": snapshot.reviewed_success_count,
                    "total_success_count": snapshot.total_success_count,
                    "unreviewed_ids": snapshot.unreviewed_ids,
                    "current_revisions": [
                        revision.model_dump(mode="json") for revision in snapshot.current_revisions
                    ],
                }
            ),
        )

    def _success_prediction(self, run: RunRecord, record_id: str) -> SuccessfulPrediction:
        for prediction in run.predictions:
            if isinstance(prediction, SuccessfulPrediction) and prediction.id == record_id:
                return prediction
        raise ReviewTargetUnavailable(record_id)

    def _validate_result(
        self, run: RunRecord, record_id: str, result: ClassificationResult
    ) -> ClassificationResult:
        validated = ClassificationResult.model_validate(result.model_dump(mode="python"))
        record = next((item for item in run.records if item.id == record_id), None)
        if record is None:
            raise ReviewTargetUnavailable(record_id)
        for judgement in validated.claims:
            validate_claim_quote(judgement.claim, record.system_reply)
            if judgement.evidence is not None:
                try:
                    validate_evidence_quote(judgement.evidence, record.knowledge_base)
                except ValueError as error:
                    raise ValueError(f"evidence {error}") from error
        for omission in validated.omissions:
            try:
                validate_evidence_quote(omission.evidence, record.knowledge_base)
            except ValueError as error:
                raise ValueError(f"evidence {error}") from error
        expected = aggregate(list(validated.claims), list(validated.omissions), validated.summary)
        if not model_equal(expected, validated):
            raise ValueError("aggregate")
        return validated
