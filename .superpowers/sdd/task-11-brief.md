### Task 11: Detection and Run Application Services

**Files:**
- Create: `src/application/run_service.py`
- Create: `src/application/detection_service.py`
- Create: `src/application/models.py`
- Create: `tests/unit/test_application_services.py`
- Create: `tests/unit/test_application_boundaries.py`

**Interfaces:**
- Produces: `RunService.create/start/progress/cancel/retry_failed/freeze/create_child`; `DetectionService.execute(run_id, record_ids=None)`; application DTOs and typed errors independent of FastAPI.
- Consumes: loaders, baseline loader, detector, registry, executor, artifact store; detection budget 200/250,000/1,800 seconds shared by first execution and pre-freeze retries.

- [ ] **Step 1: Write failing lifecycle and boundary tests**

```python
def test_all_success_auto_freezes_and_persists_snapshot() -> None:
    service = run_service(detector=all_success_detector())
    summary = service.create(create_request(), benchmark_reply_bytes())
    service.wait_for_test(summary.run_id)
    run = service.progress(summary.run_id)
    assert run.state is RunState.FROZEN
    assert run.success_count == 20 and run.failure_count == 0
    assert artifact_store().exists(run.id, "prediction_snapshot.json")


def test_partial_retry_only_replaces_requested_failure_before_freeze() -> None:
    service = run_service(detector=one_failure_then_success("h03"))
    run_id = service.create(create_request(), two_reply_bytes()).run_id
    service.wait_for_test(run_id)
    assert service.progress(run_id).state is RunState.RETRYABLE_PARTIAL
    service.retry_failed(run_id, "h03", request_id="retry-1")
    service.wait_for_test(run_id)
    assert [item.id for item in service.snapshot(run_id).results] == ["h01", "h03"]


def test_application_modules_do_not_import_fastapi() -> None:
    for path in Path("src/application").glob("*.py"):
        assert "fastapi" not in path.read_text(encoding="utf-8")
```

Also test missing provider config creates no run, empty knowledge-base warning, frozen retry creates a label-free child, partial explicit freeze, usage/attempt totals, provider-usage stop propagation, model drift, cancel marking current incomplete and subsequent records in order, fake-clock deadline, executor busy 409-domain error, and write failure preserving memory state while reporting not persisted.

- [ ] **Step 2: Confirm RED**

Run: `python -m pytest tests/unit/test_application_services.py tests/unit/test_application_boundaries.py -q`

Expected: FAIL because the application orchestration is missing.

- [ ] **Step 3: Implement creation and task orchestration**

```python
def create(self, request: CreateRunRequest, raw: bytes) -> RunSummary:
    records = load_reply_batch(raw)
    provider_config = ProviderConfig.from_environment(self.environment)
    detector = self.baselines.load()
    run = self.registry.create(records=records, config=request.config,
        input_hash=reply_input_hash(records), detector_config_hash=content_hash(detector),
        provider_model=provider_config.model)
    self.registry.transition(run.id, RunState.RUNNING)
    self.executor.submit(run.id, lambda: self.detection.execute(run.id))
    return summarize(run, empty_knowledge_base_warning(records))
```

On terminal execution, preserve all completed records, synthesize failures only for incomplete/current-and-later records, ensure `network_attempt_count == sum(result.attempt_count)`, auto-freeze only when all succeed, otherwise enter `retryable_partial`, and persist metadata plus frozen snapshot. A cancelled idle run returns its current status idempotently.

For every record, metadata stores stage logical-call counts, network attempts, provider usage, retry status categories, structural-repair flag, start/end UTC timestamps, actual model, and sanitized failure summary. Run metadata additionally stores parent ID, transition timeline, monotonic deadline, cancellation request time, stop reason, success/failure counts, review switch/coverage/snapshot hash, and independent evaluation/suggestion statuses.

- [ ] **Step 4: Verify services and architecture**

Run: `python -m pytest tests/unit/test_application_services.py tests/unit/test_application_boundaries.py tests/isolation/test_detection_label_isolation.py -q`

Expected: PASS; no application service imports FastAPI, and no suggestion service exposes detector/config/activation writes.

- [ ] **Step 5: Request approval and commit**

```powershell
git add src/application tests/unit/test_application_services.py tests/unit/test_application_boundaries.py tests/isolation/test_detection_label_isolation.py
git commit -m "feat: orchestrate bounded detection runs"
```

