from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Any, TypeVar
from uuid import uuid4

from src.domain.enums import RunState
from src.domain.hashing import content_hash, utc_now
from src.domain.models import DetectionRunConfig, ReplyRecord


class RunStateConflict(RuntimeError):
    pass


class IdempotencyConflict(RuntimeError):
    pass


ALLOWED_TRANSITIONS = {
    RunState.created: frozenset({RunState.running}),
    RunState.running: frozenset({RunState.frozen, RunState.retryable_partial, RunState.abandoned}),
    RunState.retryable_partial: frozenset({RunState.running, RunState.frozen, RunState.abandoned}),
    RunState.frozen: frozenset(),
    RunState.abandoned: frozenset(),
}


def transition_state(source: RunState, target: RunState) -> RunState:
    if target not in ALLOWED_TRANSITIONS[source]:
        raise RunStateConflict(f"cannot transition run from {source.value} to {target.value}")
    return target


@dataclass(slots=True)
class RunRecord:
    id: str
    records: tuple[ReplyRecord, ...]
    config: DetectionRunConfig
    input_hash: str
    detector_config_hash: str
    provider_model: str
    created_at: datetime
    parent_run_id: str | None = None
    state: RunState = RunState.created
    predictions: tuple[Any, ...] = field(default_factory=tuple)
    prediction_hash: str | None = None


ResultT = TypeVar("ResultT")


class RunRegistry:
    def __init__(
        self,
        *,
        uuid_factory: Callable[[], object] = uuid4,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._uuid_factory = uuid_factory
        self._clock = clock
        self._runs: dict[str, RunRecord] = {}
        self._idempotency: dict[str, tuple[str, object]] = {}
        self._lock = Lock()

    def create(
        self,
        *,
        records: Sequence[ReplyRecord],
        config: DetectionRunConfig,
        input_hash: str,
        detector_config_hash: str,
        provider_model: str,
        parent_run_id: str | None = None,
    ) -> RunRecord:
        run = RunRecord(
            id=str(self._uuid_factory()),
            records=tuple(records),
            config=config,
            input_hash=input_hash,
            detector_config_hash=detector_config_hash,
            provider_model=provider_model,
            created_at=self._clock(),
            parent_run_id=parent_run_id,
        )
        with self._lock:
            self._runs[run.id] = run
        return run

    def create_child(self, parent_run_id: str) -> RunRecord:
        parent = self.get(parent_run_id)
        return self.create(
            records=parent.records,
            config=parent.config,
            input_hash=parent.input_hash,
            detector_config_hash=parent.detector_config_hash,
            provider_model=parent.provider_model,
            parent_run_id=parent.id,
        )

    def get(self, run_id: str) -> RunRecord:
        with self._lock:
            return self._runs[run_id]

    def transition(self, run_id: str, target: RunState) -> RunRecord:
        with self._lock:
            run = self._runs[run_id]
            run.state = transition_state(run.state, target)
            return run

    def set_predictions(self, run_id: str, predictions: Sequence[Any]) -> RunRecord:
        with self._lock:
            run = self._runs[run_id]
            if run.state not in {RunState.running, RunState.retryable_partial}:
                raise RunStateConflict(f"cannot replace predictions while run is {run.state.value}")
            run.predictions = tuple(predictions)
            run.prediction_hash = content_hash(run.predictions)
            return run

    def record_idempotent(
        self,
        request_id: str,
        request_hash: str,
        operation: Callable[[], ResultT],
    ) -> ResultT:
        with self._lock:
            existing = self._idempotency.get(request_id)
            if existing is not None:
                existing_hash, result = existing
                if existing_hash != request_hash:
                    raise IdempotencyConflict(
                        f"request {request_id!r} was replayed with a different body"
                    )
                return result  # type: ignore[return-value]
            result = operation()
            self._idempotency[request_id] = (request_hash, result)
            return result
