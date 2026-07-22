"""Lifecycle orchestration for bounded in-process detection runs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import Future
import os
from threading import Event
from typing import Any

from src.application.detection_service import DetectionService
from src.application.models import (
    CreateRunRequest,
    ExecutorUnavailable,
    ProviderConfigurationUnavailable,
    RunNotFreezable,
    RunNotRetryable,
    RunProgress,
    RunSummary,
)
from src.domain.enums import RunState
from src.domain.hashing import content_hash
from src.domain.models import (
    BaselineDetectorConfig,
    BatchDetectionResult,
    FailedPrediction,
    SuccessfulPrediction,
)
from src.infrastructure.in_process_executor import ExecutorBusy, InProcessExecutor
from src.infrastructure.run_registry import RunRegistry
from src.input.loader import load_reply_batch, reply_input_hash
from src.providers.llm_provider import ProviderConfig, ProviderConfigurationError


class RunService:
    def __init__(
        self,
        registry: RunRegistry,
        detection: DetectionService,
        executor: InProcessExecutor,
        *,
        detector: BaselineDetectorConfig,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._registry = registry
        self._detection = detection
        self._executor = executor
        self._detector = detector
        self._environment = os.environ if environment is None else environment
        self._futures: dict[str, Future[Any]] = {}
        self._warnings: dict[str, tuple[str, ...]] = {}
        self._run_ids: set[str] = set()
        self._retry_requests: dict[str, tuple[str, RunSummary]] = {}

    def create(self, request: CreateRunRequest, raw: bytes) -> RunSummary:
        try:
            provider_config = ProviderConfig.from_environment(self._environment)
        except ProviderConfigurationError as error:
            raise ProviderConfigurationUnavailable(
                "provider configuration is unavailable"
            ) from error
        if self._executor.is_busy():
            raise ExecutorUnavailable("detection worker is busy")
        records = load_reply_batch(raw)
        run = self._registry.create(
            records=records,
            config=request.config,
            input_hash=reply_input_hash(records),
            detector_config_hash=content_hash(self._detector),
            provider_model=provider_config.model,
        )
        self._run_ids.add(run.id)
        self._warnings[run.id] = _warnings(records)
        self._registry.transition(run.id, RunState.running)
        self._submit(run.id)
        return self._summary(run.id)

    def start(self, run_id: str, record_ids: Sequence[str] | None = None) -> RunSummary:
        run = self._registry.get(run_id)
        if run.state is not RunState.running:
            raise RuntimeError("run is not ready to start")
        self._submit(run_id, record_ids)
        return self._summary(run_id)

    def progress(self, run_id: str) -> RunProgress:
        run = self._registry.get(run_id)
        successes = sum(isinstance(item, SuccessfulPrediction) for item in run.predictions)
        failures = sum(isinstance(item, FailedPrediction) for item in run.predictions)
        persistence_error = self._detection.persistence_error(run_id)
        return RunProgress(
            id=run.id,
            state=run.state,
            total_count=len(run.records),
            completed_count=successes + failures,
            success_count=successes,
            failure_count=failures,
            warnings=self._warnings.get(run_id, _warnings(run.records)),
            persisted=persistence_error is None,
            persistence_error=persistence_error,
            parent_run_id=run.parent_run_id,
        )

    def cancel(self, run_id: str) -> RunProgress:
        run = self._registry.get(run_id)
        if run.state in {RunState.frozen, RunState.abandoned}:
            return self.progress(run_id)
        if self._executor.cancel(run_id):
            self._registry.transition(run_id, RunState.abandoned)
        return self.progress(run_id)

    def retry_failed(self, run_id: str, record_id: str, *, request_id: str) -> RunSummary:
        run = self._registry.get(run_id)
        if run.state is not RunState.retryable_partial:
            raise RunNotRetryable(run_id)
        failed_ids = {item.id for item in run.predictions if isinstance(item, FailedPrediction)}
        if record_id not in failed_ids:
            raise RunNotRetryable(record_id)

        request_hash = content_hash({"run_id": run_id, "record_id": record_id})
        existing = self._retry_requests.get(request_id)
        if existing is not None:
            if existing[0] != request_hash:
                raise ValueError("retry request id was replayed with a different body")
            return existing[1]
        self._registry.transition(run_id, RunState.running)
        self._submit(run_id, [record_id])
        summary = self._summary(run_id)
        self._retry_requests[request_id] = (request_hash, summary)
        return summary

    def freeze(self, run_id: str) -> RunSummary:
        if self._registry.get(run_id).state is not RunState.retryable_partial:
            raise RunNotFreezable(run_id)
        self._detection.freeze(run_id)
        return self._summary(run_id)

    def create_child(self, run_id: str) -> RunProgress:
        parent = self._registry.get(run_id)
        if parent.state is not RunState.frozen:
            raise RuntimeError("only a frozen run can create a child")
        child = self._registry.create_child(run_id)
        self._run_ids.add(child.id)
        self._warnings[child.id] = _warnings(child.records)
        return self.progress(child.id)

    def snapshot(self, run_id: str) -> BatchDetectionResult:
        return self._detection.snapshot(run_id)

    def wait_for_test(self, run_id: str) -> None:
        self._futures[run_id].result(timeout=5)

    def run_count_for_test(self) -> int:
        return len(self._run_ids)

    def _submit(self, run_id: str, record_ids: Sequence[str] | None = None) -> None:
        def task(cancel_event: Event) -> None:
            del cancel_event
            self._detection.execute(run_id, record_ids)

        try:
            self._futures[run_id] = self._executor.submit(run_id, task)
        except ExecutorBusy as error:
            raise ExecutorUnavailable("detection worker is busy") from error

    def _summary(self, run_id: str) -> RunSummary:
        run = self._registry.get(run_id)
        return RunSummary(run.id, run.state, self._warnings.get(run_id, ()), run.parent_run_id)


def _warnings(records: Sequence[object]) -> tuple[str, ...]:
    if any(getattr(record, "knowledge_base", None) == "" for record in records):
        return ("empty knowledge_base",)
    return ()
