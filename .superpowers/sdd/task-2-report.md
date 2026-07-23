# Task 2 Report: Canonical Serialization, Enums, and Boundary Models

## Status

Completed and committed as `255a1c2` (`feat: define immutable domain contracts and
canonical hashes`).

## User-approved scope adjustment

The approved design did not define fields for `ProgressEvent`, `PredictionSnapshot`,
`ReviewSnapshot`, `ErrorAnalysisInput`, or `ExperimentalSuggestionBody`. The user
approved deferring those five models until their first real consumer task, where their
fields will be defined through TDD against the actual interface. Task 2 therefore
implements only contracts whose fields and invariants are explicit in the brief and
approved design. `ArtifactStatus` is included from the explicit section 4.4 values.

## RED evidence

Command:

```text
python -m pytest tests/unit/test_canonical_hash.py tests/unit/test_claim_invariants.py tests/unit/test_evidence_reference.py tests/unit/test_prediction_result.py -q
```

Observed expected RED: exit code 1 during collection with four import errors:

- `No module named 'src.domain.hashing'`
- `No module named 'src.domain.enums'` (three test modules)

This demonstrated that the focused tests depended on the missing Task 2 implementation.

## GREEN evidence

The same focused command passed after the minimum implementation:

```text
37 passed in 2.91s
```

After formatting and the small validator refactor, the fresh focused rerun was:

```text
37 passed in 0.64s
```

## Implementation

- Added fixed-order serialized enums for hallucination labels, severity, run state,
  and artifact status.
- Added canonical compact UTF-8 JSON bytes, top-level self-hash exclusion, SHA-256
  content hashes, and aware UTC timestamps.
- Added frozen, strict, `extra="forbid"` Pydantic v2 contracts defined by the approved
  design.
- Added stable ID normalization, illegal C0 rejection, Unicode code-point quote
  validation, exact length/offset boundaries, verdict and classification invariants,
  stable label de-duplication, prediction discriminators, network-attempt accounting,
  UTC `Z` serialization, revision event-chain hashes, risk-reference self-hashes,
  ground-truth invariants, baseline definition key sets, error-analysis constraints,
  and suggestion/report limits.

## Files committed

- `src/domain/enums.py`
- `src/domain/hashing.py`
- `src/domain/models.py`
- `tests/unit/test_canonical_hash.py`
- `tests/unit/test_claim_invariants.py`
- `tests/unit/test_evidence_reference.py`
- `tests/unit/test_prediction_result.py`

Protected inputs, approved documents, Task 1 packaging/resources, and unrelated
untracked files were not modified or staged.

## Final verification

All commands ran from the repository root before commit:

```text
python -m pytest -q
42 passed in 0.61s

python -m ruff check .
All checks passed!

python -m ruff format --check .
23 files already formatted

python -m mypy src tests
Success: no issues found in 23 source files

python -m build
Successfully built xiaoduo_hallucination_dashboard-0.1.0.tar.gz and
xiaoduo_hallucination_dashboard-0.1.0-py3-none-any.whl
```

Build emitted the existing non-blocking warning that no README file is present.

## Self-review and concerns

No P0/P1 correctness, security, isolation, or scope findings remained in the Task 2
change. The models are deliberately limited to authoritative fields; service-level
checks requiring external context (batch ID uniqueness, exact case-set equality,
source-prediction equivalence, prompt/suggestion content whitelist checks, and the five
deferred schemas) remain for their designated later tasks.

## Review remediation

All five Important findings from the Task 2 review were fixed and committed as
`2cd0fc0` (`fix: harden immutable domain contract invariants`).

### 1. Deep immutability

RED reproduced three shallow-freeze defects: `RiskReference.severity_by_positive_id`
accepted item assignment, `ClassificationResult.claims`/`omissions` accepted in-place
clearing, and `HumanReviewRevision.changed_fields` accepted append. The three focused
tests failed as expected.

GREEN uses immutable internal sequence and mapping containers across every domain
list/dict field, while Pydantic serializers retain JSON arrays/objects and list-based
construction/comparison compatibility. Focused result: `3 passed` with no serializer
warnings.

### 2. Duplicate aggregate IDs

RED: duplicate `claim_id` and duplicate `omission_id` were both accepted (`2 failed`).
GREEN: `ClassificationResult` now rejects each duplicate set (`2 passed`).

### 3. Baseline prompt whitelist

RED: blank/missing-boundary prompts and explicit template, URL, path, code-fence, and
command-substitution payloads were accepted (`7 failed`, while the negative-language
control passed). GREEN: all five prompts must be non-empty and contain
`UNTRUSTED_DATA`; explicit unsafe syntax is rejected without rejecting Chinese
instructions that prohibit file/network/system operations (`9 passed`).

### 4. SHA-256 field shape

RED: the JSON schemas lacked the SHA-256 pattern and short, uppercase, and non-hex
config hashes were accepted (`4 failed`). GREEN: the common 64-character lowercase
hex type covers successful config hashes, batch input/config hashes, revision source
and event-chain hashes, risk-reference hashes, and suggestion-report input/prediction/
config hashes (`6 passed`, including event-chain and risk-reference regression tests).

### 5. FailedPrediction attempt counts

RED: all seven failure codes that imply Provider/network work accepted zero attempts
(`7 failed`); the four pre-network stop codes passed. GREEN: only
`request_budget_exhausted`, `token_budget_exhausted`, `cancelled`, and
`run_deadline_exceeded` may use zero (`11 passed`).

### Post-remediation verification

Fresh results after all fixes:

```text
Task 2 focused tests: 63 passed in 1.07s
python -m pytest -q: 68 passed in 1.26s
python -m ruff check .: All checks passed!
python -m ruff format --check .: 23 files already formatted
python -m mypy src tests: Success: no issues found in 23 source files
python -m build: wheel and sdist built successfully
```

The existing build warning about the absent README remains non-blocking.

### Remediation concern

Per the explicit scope restriction, no read-only resource was modified. The current
`baseline.json` suggestion prompt predates the new all-five-prompts
`UNTRUSTED_DATA` requirement and does not contain that literal marker. The later
configuration-loader task must surface this as a safe configuration error unless a
separate protected-resource change is approved; the Task 2 validator does not silently
weaken the new whitelist.
