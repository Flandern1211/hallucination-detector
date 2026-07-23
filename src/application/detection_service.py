"""Detection execution and frozen prediction snapshots."""

from __future__ import annotations

from collections.abc import Sequence
import logging
from typing import Any, Protocol, cast

from src.domain.enums import RunState
from src.domain.models import (
    BaselineDetectorConfig,
    BatchDetectionResult,
    FailedPrediction,
    PredictionResult,
    ProviderUsage,
    ReplyRecord,
    SuccessfulPrediction,
)
from src.infrastructure.artifact_store import ArtifactStore
from src.infrastructure.run_registry import RunRegistry
from src.reporting.exporter import export_predictions

logger = logging.getLogger("hallucination.run")


class BatchDetector(Protocol):
    def detect_batch(
        self, records: list[ReplyRecord], detector: BaselineDetectorConfig
    ) -> BatchDetectionResult: ...


class DetectionService:
    def __init__(
        self,
        registry: RunRegistry,
        engine: BatchDetector,
        detector: BaselineDetectorConfig,
        *,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self._registry = registry
        self._engine = engine
        self._detector = detector
        self._artifact_store = artifact_store
        self._snapshots: dict[str, BatchDetectionResult] = {}
        self._persistence_errors: dict[str, str] = {}
        self._usage: dict[str, ProviderUsage] = {}
        self._stopped_reasons: dict[str, str | None] = {}
        self._progress: dict[str, tuple[int, int, int]] = {}

    def execute(self, run_id: str, record_ids: Sequence[str] | None = None) -> BatchDetectionResult:
        run = self._registry.get(run_id)
        records = self._select_records(run.records, record_ids)
        total = len(records)

        def on_progress(event: object) -> None:
            completed = int(getattr(event, "completed_count", 0))
            successes = int(getattr(event, "outcome", "") == "success")
            previous = self._progress.get(run_id, (0, 0, 0))
            self._progress[run_id] = (
                completed,
                previous[1] + successes,
                completed - (previous[1] + successes),
            )
            logger.info(
                "run_record_completed run_id=%s record=%s progress=%d/%d outcome=%s",
                run_id,
                getattr(event, "record_id", "unknown"),
                completed,
                total,
                getattr(event, "outcome", "unknown"),
            )

        try:
            batch = cast(Any, self._engine).detect_batch(
                list(records), self._detector, on_progress=on_progress
            )
        except TypeError as error:
            if "on_progress" not in str(error):
                raise
            batch = self._engine.detect_batch(list(records), self._detector)
        self._usage[run_id] = _add_usage(
            self._usage.get(run_id, _zero_usage()), batch.provider_usage
        )
        self._stopped_reasons[run_id] = batch.stopped_reason
        predictions = self._merge_predictions(run.records, run.predictions, batch.results)
        logger.info(
            "run_batch_completed run_id=%s total=%d successes=%d failures=%d",
            run_id,
            len(predictions),
            sum(isinstance(item, SuccessfulPrediction) for item in predictions),
            sum(isinstance(item, FailedPrediction) for item in predictions),
        )
        self._registry.set_predictions(run_id, predictions)
        snapshot = self._snapshot(run_id)
        if all(isinstance(item, SuccessfulPrediction) for item in predictions):
            self._registry.transition(run_id, RunState.frozen)
            self._persist_snapshot(run_id, snapshot)
        else:
            self._registry.transition(run_id, RunState.retryable_partial)
        return snapshot

    def freeze(self, run_id: str) -> BatchDetectionResult:
        run = self._registry.get(run_id)
        if run.state is not RunState.retryable_partial:
            raise RuntimeError("only a partial run can be explicitly frozen")
        snapshot = self._snapshot(run_id)
        self._registry.transition(run_id, RunState.frozen)
        self._persist_snapshot(run_id, snapshot)
        return snapshot

    def snapshot(self, run_id: str) -> BatchDetectionResult:
        return self._snapshots.get(run_id) or self._snapshot(run_id)

    def persistence_error(self, run_id: str) -> str | None:
        return self._persistence_errors.get(run_id)

    def progress_counts(self, run_id: str) -> tuple[int, int, int] | None:
        return self._progress.get(run_id)

    def _snapshot(self, run_id: str) -> BatchDetectionResult:
        run = self._registry.get(run_id)
        results = list(run.predictions)
        if not results:
            raise RuntimeError("run has no prediction snapshot")
        snapshot = BatchDetectionResult(
            schema_version="1.0",
            results=results,
            input_hash=run.input_hash,
            detector_config_hash=run.detector_config_hash,
            network_attempt_count=sum(item.attempt_count for item in results),
            provider_usage=self._usage.get(run_id, _zero_usage()),
            stopped_reason=self._stopped_reasons.get(run_id),
        )
        self._snapshots[run_id] = snapshot
        return snapshot

    def _persist_snapshot(self, run_id: str, snapshot: BatchDetectionResult) -> None:
        if self._artifact_store is None:
            return
        try:
            self._artifact_store.write_json(
                run_id, "prediction_snapshot.json", snapshot.model_dump(mode="json")
            )
            self._artifact_store.write_json(
                run_id,
                "predictions.json",
                export_predictions({"run_id": run_id, **snapshot.model_dump(mode="json")}),
            )
        except OSError as error:
            self._persistence_errors[run_id] = str(error)

    @staticmethod
    def _select_records(
        records: tuple[ReplyRecord, ...], record_ids: Sequence[str] | None
    ) -> tuple[ReplyRecord, ...]:
        if record_ids is None:
            return records
        selected = set(record_ids)
        if not selected:
            raise ValueError("at least one record id is required")
        result = tuple(record for record in records if record.id in selected)
        if len(result) != len(selected):
            raise KeyError("unknown record id")
        return result

    @staticmethod
    def _merge_predictions(
        records: tuple[ReplyRecord, ...],
        existing: tuple[object, ...],
        updates: Sequence[PredictionResult],
    ) -> list[PredictionResult]:
        by_id = {
            item.id: item
            for item in existing
            if isinstance(item, (SuccessfulPrediction, FailedPrediction))
        }
        by_id.update({item.id: item for item in updates})
        missing_ids = [record.id for record in records if record.id not in by_id]
        if missing_ids:
            raise RuntimeError("detector did not return every requested prediction")
        return [by_id[record.id] for record in records]


def _zero_usage() -> ProviderUsage:
    return ProviderUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)


def _add_usage(left: ProviderUsage, right: ProviderUsage) -> ProviderUsage:
    return ProviderUsage(
        prompt_tokens=left.prompt_tokens + right.prompt_tokens,
        completion_tokens=left.completion_tokens + right.completion_tokens,
        total_tokens=left.total_tokens + right.total_tokens,
    )
