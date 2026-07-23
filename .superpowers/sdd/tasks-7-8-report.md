# Tasks 7–8 Implementation Report

Date: 2026-07-23

## Completed

### Task 7 — Append-Only Human Review

- Added server-owned result diffs with deterministic JSON-pointer-like field paths.
- Added a locked, in-process append-only revision store with idempotent `save_request_id`
  replay, per-record monotonic revision numbers, and chained event hashes.
- Added `ReviewService.save`, `restore_original`, and `review_snapshot`.
- Enforced frozen-run and manual-review gates, successful-prediction-only targets, source
  prediction hash conflicts, confirmed-result equality, evidence offsets, aggregation rules,
  server UUID/time/diff/hash ownership, and stable successful-record review coverage.
- Preserved frozen prediction hashes across confirmation, correction, and restore operations.

### Task 8 — Official Evaluation, Risk Reference, and Metrics

- Added nullable metric values with explicit numerator, denominator, and zero-denominator reason.
- Added prediction/ground-truth ID alignment, failure exclusion, coverage/completeness, confusion
  counts, precision, recall, F1, specificity, Macro-F1, balanced accuracy, primary-type match,
  high-risk recall, and FN/FP ID sets.
- Added versioned manual-type compatibility loading with unknown-type reporting.
- Added uploaded-severity and frozen-benchmark risk-reference selection. Partial uploaded
  severities never fall back to the benchmark; mismatched or incomplete references yield a null
  high-risk recall.
- Added `EvaluationService.load_ground_truth` and `evaluate` with frozen-run gating, normalized
  used-field persistence, single-content-hash conflict protection, and idempotent results.
- Kept official labels and risk references outside the detection dependency graph and verified
  frozen prediction hashes remain unchanged.

### Supporting correction

- Fixed canonical hashing so Pydantic models nested inside lists/tuples are recursively normalized;
  this was required for `RunRegistry` to freeze real prediction objects.

## Verification

Fresh commands run from the repository root:

```text
python -m pytest tests/unit/test_review_revision.py tests/unit/test_metrics.py tests/unit/test_risk_reference.py tests/unit/test_canonical_hash.py tests/isolation/test_detection_label_isolation.py -q
Result: 19 passed in 2.72s

python -m ruff check <Task 7–8 changed Python files>
Result: All checks passed

python -m ruff format --check <Task 7–8 changed Python files>
Result: 14 files already formatted

python -m mypy <Task 7–8 changed Python files>
Result: Success: no issues found in 14 source files
```

## Not performed

- No Git commit, push, PR, deployment, real external LLM call, full-suite test, or full build was
  performed, per the delegated task boundary.

## Files

- `src/domain/hashing.py`
- `src/domain/models.py`
- `src/domain/metrics.py`
- `src/review/diff.py`
- `src/review/revision_store.py`
- `src/application/review_service.py`
- `src/evaluation/type_mapping.py`
- `src/evaluation/evaluator.py`
- `src/application/evaluation_service.py`
- `tests/unit/test_canonical_hash.py`
- `tests/unit/test_review_revision.py`
- `tests/unit/test_metrics.py`
- `tests/unit/test_risk_reference.py`
- `tests/isolation/test_detection_label_isolation.py`
