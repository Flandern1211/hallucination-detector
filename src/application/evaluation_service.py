"""Application service for loading official labels after prediction freeze."""

from __future__ import annotations

from threading import Lock
from typing import Literal

from pydantic import Field

from src.domain.enums import RunState
from src.domain.metrics import EvaluationResult
from src.domain.models import GroundTruthRecord, RiskReference, Sha256Hex, StrictModel
from src.evaluation.evaluator import choose_risk_reference, evaluate, ground_truth_hash
from src.evaluation.type_mapping import TypeCompatibility
from src.infrastructure.artifact_store import ArtifactStore
from src.infrastructure.run_registry import RunRegistry
from src.input.loader import load_ground_truth_batch
from src.reporting.exporter import export_evaluation
from src.suggestions.error_analyzer import OfficialSource


class GroundTruthConflict(RuntimeError):
    pass


class GroundTruthSummary(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    content_hash: Sha256Hex
    record_count: int = Field(ge=1)
    positive_count: int = Field(ge=0)
    risk_reference_source: Literal["uploaded_ground_truth", "frozen_benchmark_map"] | None


class EvaluationService:
    def __init__(
        self,
        registry: RunRegistry,
        type_map: TypeCompatibility,
        *,
        benchmark_risk_reference: RiskReference | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self._registry = registry
        self._type_map = type_map
        self._benchmark = benchmark_risk_reference
        self._artifact_store = artifact_store
        self._ground_truth: dict[
            str, tuple[str, tuple[GroundTruthRecord, ...], RiskReference | None]
        ] = {}
        self._summaries: dict[str, GroundTruthSummary] = {}
        self._evaluations: dict[str, EvaluationResult] = {}
        self._lock = Lock()

    def load_ground_truth(self, run_id: str, raw: bytes, request_id: str) -> GroundTruthSummary:
        del request_id  # Content-bound idempotency is stricter than transport retry identity.
        run = self._registry.get(run_id)
        if run.state is not RunState.frozen:
            raise RuntimeError("ground truth requires a frozen run")
        records = load_ground_truth_batch(raw)
        source_hash = ground_truth_hash(records)
        reference = choose_risk_reference(records, self._benchmark)
        summary = GroundTruthSummary(
            run_id=run_id,
            content_hash=source_hash,
            record_count=len(records),
            positive_count=sum(record.is_hallucination for record in records),
            risk_reference_source=None if reference is None else reference.source,
        )
        with self._lock:
            existing = self._ground_truth.get(run_id)
            if existing is not None:
                if existing[0] != source_hash:
                    raise GroundTruthConflict(run_id)
                return self._summaries[run_id]
            if self._artifact_store is not None:
                self._artifact_store.write_json(
                    run_id,
                    "ground_truth.normalized.json",
                    [record.model_dump(mode="json") for record in records],
                )
            self._ground_truth[run_id] = (source_hash, tuple(records), reference)
            self._summaries[run_id] = summary
            return summary

    def evaluate(self, run_id: str, request_id: str) -> EvaluationResult:
        del request_id
        run = self._registry.get(run_id)
        if run.state is not RunState.frozen:
            raise RuntimeError("evaluation requires a frozen run")
        with self._lock:
            cached = self._evaluations.get(run_id)
            if cached is not None:
                return cached
            try:
                _, records, reference = self._ground_truth[run_id]
            except KeyError as error:
                raise RuntimeError("ground truth has not been loaded") from error
            result = evaluate(list(run.predictions), list(records), reference, self._type_map)
            if self._artifact_store is not None:
                self._artifact_store.write_json(
                    run_id,
                    "evaluation.json",
                    export_evaluation({"run_id": run_id, **result.model_dump(mode="json")}),
                )
            self._evaluations[run_id] = result
            return result

    def official_source(self, run_id: str) -> OfficialSource:
        run = self._registry.get(run_id)
        try:
            _, records, _ = self._ground_truth[run_id]
        except KeyError as error:
            raise RuntimeError("ground truth has not been loaded") from error
        run_ids = {record.id for record in run.records}
        selected = tuple(record for record in records if record.id in run_ids)
        return OfficialSource(
            labels=selected,
            coverage=len(selected) / len(run.records),
        )


__all__ = ["EvaluationService", "GroundTruthConflict", "GroundTruthSummary"]
