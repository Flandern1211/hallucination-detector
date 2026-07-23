### Task 6: Run State, Idempotency, Single Executor, and Safe Artifact Store

**Files:**
- Create: `src/infrastructure/run_registry.py`
- Create: `src/infrastructure/in_process_executor.py`
- Create: `src/infrastructure/artifact_store.py`
- Create: `tests/unit/test_run_state.py`
- Create: `tests/unit/test_artifact_store.py`
- Create: `tests/unit/test_executor.py`

**Interfaces:**
- Produces: `RunRegistry.create/get/transition/record_idempotent`; `RunRecord`; `InProcessExecutor.submit/cancel/is_busy/shutdown` using `ThreadPoolExecutor(max_workers=1)`; `ArtifactStore.write_json/read_json/append_revision/export_path`; `RunStateConflict`, `IdempotencyConflict`, `UnsafeArtifactPath`, `ArtifactCorrupt`.
- Consumes: canonical hashes/models, explicit workspace `runtime_root: Path`, injected UUID and clock functions.

- [ ] **Step 1: Write failing state and storage tests**

```python
@pytest.mark.parametrize(("source", "target"), [
    (RunState.CREATED, RunState.RUNNING),
    (RunState.RUNNING, RunState.FROZEN),
    (RunState.RUNNING, RunState.RETRYABLE_PARTIAL),
    (RunState.RETRYABLE_PARTIAL, RunState.RUNNING),
    (RunState.RETRYABLE_PARTIAL, RunState.FROZEN),
])
def test_legal_run_transitions(source: RunState, target: RunState) -> None:
    assert transition_state(source, target) is target


def test_frozen_run_cannot_mutate_prediction_hash() -> None:
    run = frozen_run(prediction_hash="a" * 64)
    with pytest.raises(RunStateConflict):
        run.replace_predictions(batch_result())


def test_artifact_store_rejects_escape_and_corrupt_json(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "runtime")
    with pytest.raises(UnsafeArtifactPath):
        store.export_path("run-1", "../task4_replies.json")
    path = store.write_json("run-1", "prediction_snapshot.json", snapshot())
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ArtifactCorrupt):
        store.read_json("run-1", "prediction_snapshot.json", PredictionSnapshot)
```

- [ ] **Step 2: Confirm RED**

Run: `python -m pytest tests/unit/test_run_state.py tests/unit/test_artifact_store.py tests/unit/test_executor.py -q`

Expected: FAIL on missing infrastructure modules.

- [ ] **Step 3: Implement the explicit transition table and idempotency key store**

```python
ALLOWED_TRANSITIONS = {
    RunState.CREATED: frozenset({RunState.RUNNING}),
    RunState.RUNNING: frozenset({RunState.FROZEN, RunState.RETRYABLE_PARTIAL,
                                 RunState.ABANDONED}),
    RunState.RETRYABLE_PARTIAL: frozenset({RunState.RUNNING, RunState.FROZEN,
                                           RunState.ABANDONED}),
    RunState.FROZEN: frozenset(),
    RunState.ABANDONED: frozenset(),
}


def transition_state(source: RunState, target: RunState) -> RunState:
    if target not in ALLOWED_TRANSITIONS[source]:
        raise RunStateConflict(source, target)
    return target
```

Store `request_id -> (request_hash, result)` under the registry lock; return the result for an identical replay and raise `IdempotencyConflict` for a changed body. Child runs copy only records/config, set `parent_run_id`, and start without predictions, labels, evaluation, reviews, or suggestions.

- [ ] **Step 4: Implement safe atomic persistence and one active external task**

Use `Path.resolve()` plus `is_relative_to(runtime_root.resolve())`; create temporary files in the final directory; write canonical UTF-8 JSON; `flush`, `os.fsync`, validate by reparsing, then `os.replace`. Protect the entire revision version-check/append/fsync/snapshot sequence with one lock. Ignore only an unparseable final JSONL line during reads; reject any other parse break or event-hash discontinuity.

- [ ] **Step 5: Verify infrastructure behavior**

Run: `python -m pytest tests/unit/test_run_state.py tests/unit/test_artifact_store.py tests/unit/test_executor.py -q`

Expected: PASS, including busy rejection, cooperative cancellation, frozen immutability, idempotency conflict, path escape, torn tail, and corrupt chain cases.

- [ ] **Step 6: Request approval and commit**

```powershell
git add src/infrastructure tests/unit/test_run_state.py tests/unit/test_artifact_store.py tests/unit/test_executor.py
git commit -m "feat: add in-process run state and safe artifacts"
```

