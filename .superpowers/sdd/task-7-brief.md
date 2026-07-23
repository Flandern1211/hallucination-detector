### Task 7: Append-Only Human Review

**Files:**
- Create: `src/review/diff.py`
- Create: `src/review/revision_store.py`
- Create: `src/application/review_service.py`
- Create: `tests/unit/test_review_revision.py`
- Extend: `tests/isolation/test_detection_label_isolation.py`

**Interfaces:**
- Produces: `ReviewService.save(run_id: str, record_id: str, request: ReviewSaveRequest) -> HumanReviewRevision`; `ReviewService.restore_original(run_id: str, record_id: str, save_request_id: str, source_prediction_hash: str) -> HumanReviewRevision`; `ReviewService.review_snapshot(run_id: str) -> ReviewSnapshot`; `diff_results(before: ClassificationResult, after: ClassificationResult) -> list[str]` using JSON-pointer-like field paths.
- Consumes: frozen successful prediction, registry, artifact store, server UUID/UTC clock; never receives a prediction write interface.

- [ ] **Step 1: Write failing revision, idempotency, and immutability tests**

```python
def test_confirmed_correct_appends_hash_chained_revision() -> None:
    service, run = review_service(manual_review_enabled=True)
    first = service.save(run.id, "h01", confirm_request("save-1", run.success("h01")))
    second = service.save(run.id, "h01", correction_request("save-2", corrected_result()))
    assert first.revision_number == 1 and first.previous_event_hash is None
    assert second.revision_number == 2 and second.previous_event_hash == first.event_hash
    assert second.changed_fields == ["/is_hallucination", "/labels", "/primary_type",
                                     "/severity", "/summary"]
    assert run.prediction_hash == original_prediction_hash(run)


def test_same_save_request_is_idempotent_and_stale_hash_conflicts() -> None:
    service, run = review_service(manual_review_enabled=True)
    request = confirm_request("save-1", run.success("h01"))
    assert service.save(run.id, "h01", request) == service.save(run.id, "h01", request)
    with pytest.raises(SourcePredictionConflict):
        service.save(run.id, "h01", request.model_copy(
            update={"save_request_id": "save-2", "source_prediction_hash": "0" * 64}))
```

Also test disabled review, failed predictions, `confirmed_correct` mismatch, corrected aggregation/evidence failure, restore as a new event, monotonic revision numbers, and reviewed-success coverage excluding failures.

- [ ] **Step 2: Confirm RED**

Run: `python -m pytest tests/unit/test_review_revision.py tests/isolation/test_detection_label_isolation.py -q`

Expected: FAIL because review services are absent.

- [ ] **Step 3: Implement server-owned diffs and append-only saves**

```python
def save(self, run_id: str, record_id: str,
         request: ReviewSaveRequest) -> HumanReviewRevision:
    run = self.registry.require_frozen(run_id)
    prediction = run.require_success(record_id)
    if not run.config.manual_review_enabled:
        raise ReviewDisabled(run_id)
    expected_hash = content_hash(prediction)
    if request.source_prediction_hash != expected_hash:
        raise SourcePredictionConflict(record_id)
    validate_classification(request.reviewed_result, run.record(record_id))
    return self.revisions.append_locked(run, prediction, request, self.clock())
```

`confirmed_correct` requires structural equality to `prediction.result`; `corrected` uses the same claim/evidence/aggregate validators; `changed_fields`, revision number, prior hash, event hash, IDs, and UTC timestamp are calculated only on the server.

- [ ] **Step 4: Verify review behavior**

Run: `python -m pytest tests/unit/test_review_revision.py tests/isolation/test_detection_label_isolation.py -q`

Expected: PASS and prediction hashes remain identical before and after confirm, correct, and restore operations.

- [ ] **Step 5: Request approval and commit**

```powershell
git add src/review src/application/review_service.py tests/unit/test_review_revision.py tests/isolation/test_detection_label_isolation.py
git commit -m "feat: add immutable human review history"
```

