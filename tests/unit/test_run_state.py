from datetime import UTC, datetime

import pytest

from src.domain.enums import RunState
from src.domain.hashing import content_hash
from src.domain.models import DetectionRunConfig, ReplyRecord
from src.infrastructure.run_registry import (
    IdempotencyConflict,
    RunRegistry,
    RunStateConflict,
    transition_state,
)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (RunState.created, RunState.running),
        (RunState.running, RunState.frozen),
        (RunState.running, RunState.retryable_partial),
        (RunState.retryable_partial, RunState.running),
        (RunState.retryable_partial, RunState.frozen),
    ],
)
def test_legal_run_transitions(source: RunState, target: RunState) -> None:
    assert transition_state(source, target) is target


def test_registry_freezes_predictions_and_idempotency_is_body_bound() -> None:
    registry = RunRegistry(
        uuid_factory=lambda: "run-1",
        clock=lambda: datetime(2026, 7, 23, tzinfo=UTC),
    )
    record = ReplyRecord(id="h01", user_question="q", system_reply="r", knowledge_base="")
    run = registry.create(
        records=[record],
        config=DetectionRunConfig(
            detector_version="baseline-v1", external_processing_acknowledged=True
        ),
        input_hash="a" * 64,
        detector_config_hash="b" * 64,
        provider_model="model",
    )
    registry.transition(run.id, RunState.running)
    registry.set_predictions(run.id, ["first"])
    registry.transition(run.id, RunState.frozen)
    frozen_hash = run.prediction_hash
    with pytest.raises(RunStateConflict):
        registry.set_predictions(run.id, ["changed"])
    assert run.prediction_hash == frozen_hash == content_hash(["first"])

    assert registry.record_idempotent("request-1", "hash-a", lambda: 3) == 3
    assert registry.record_idempotent("request-1", "hash-a", lambda: 4) == 3
    with pytest.raises(IdempotencyConflict):
        registry.record_idempotent("request-1", "hash-b", lambda: 4)


def test_child_copies_only_records_and_config() -> None:
    registry = RunRegistry(uuid_factory=iter(["parent", "child"]).__next__)
    record = ReplyRecord(id="h01", user_question="q", system_reply="r", knowledge_base="")
    parent = registry.create(
        records=[record],
        config=DetectionRunConfig(
            detector_version="baseline-v1", external_processing_acknowledged=True
        ),
        input_hash="a" * 64,
        detector_config_hash="b" * 64,
        provider_model="model",
    )
    registry.transition(parent.id, RunState.running)
    registry.set_predictions(parent.id, ["prediction"])
    registry.transition(parent.id, RunState.frozen)
    child = registry.create_child(parent.id)
    assert child.parent_run_id == parent.id
    assert child.records == parent.records
    assert child.predictions == ()
    assert child.state is RunState.created
