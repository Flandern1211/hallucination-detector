### Task 2: Canonical Serialization, Enums, and Boundary Models

**Files:**
- Create: `src/domain/enums.py`
- Create: `src/domain/hashing.py`
- Create: `src/domain/models.py`
- Create: `tests/unit/test_canonical_hash.py`
- Create: `tests/unit/test_prediction_result.py`
- Create: `tests/unit/test_claim_invariants.py`
- Create: `tests/unit/test_evidence_reference.py`

**Interfaces:**
- Produces: `canonical_bytes(value: Any, exclude: frozenset[str] = frozenset()) -> bytes`; `content_hash(value: Any, exclude: frozenset[str] = frozenset()) -> str`; `utc_now() -> datetime`; `HallucinationType`, `Severity`, `RunState`, `ArtifactStatus`; strict `ReplyRecord`, `Claim`, `EvidenceReference`, `ClaimJudgement`, `OmissionFinding`, `ClassificationResult`, `SuccessfulPrediction`, `FailedPrediction`, `PredictionResult`, `ProviderUsage`, `BatchDetectionResult`, `DetectionRunConfig`, `ProgressEvent`, `PredictionSnapshot`, `HumanReviewRevision`, `ReviewSnapshot`, `GroundTruthRecord`, `RiskReference`, `BaselineDetectorConfig`, `ErrorAnalysisInput`, `SuccessfulErrorAnalysis`, `FailedErrorAnalysis`, `ErrorAnalysis`, `ExperimentalSuggestionBody`, `ExperimentalSuggestion`, and `SuggestionReport`; `validate_claim_quote`, `validate_evidence_quote`, and stable ID normalization.
- Consumes: fixed enum order and contract version `1.0`.

- [ ] **Step 1: Write failing hash and invariant tests**

```python
def test_canonical_hash_ignores_key_order_and_excluded_self_hash() -> None:
    assert content_hash({"b": 2, "a": "中文"}) == content_hash({"a": "中文", "b": 2})
    assert content_hash({"a": 1, "artifact_hash": "x"}, frozenset({"artifact_hash"})) == content_hash(
        {"a": 1, "artifact_hash": "y"}, frozenset({"artifact_hash"})
    )


def test_claim_and_evidence_must_match_unicode_code_point_slices() -> None:
    reply = "答复🙂支持七天退货"
    claim = Claim(claim_id="h01-c01", text="支持七天退货", source_quote="支持七天退货",
                  source_start_offset=3, source_end_offset=9, kind="policy")
    validate_claim_quote(claim, reply)
    with pytest.raises(ValueError, match="source_quote"):
        validate_claim_quote(claim.model_copy(update={"source_end_offset": 8}), reply)


def test_failed_prediction_rejects_classification_fields() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(PredictionResult).validate_python({
            "kind": "failure", "id": "h01", "error_code": "timeout",
            "error_summary": "provider timeout", "attempt_count": 1,
            "model_name": None, "result": {"is_hallucination": False},
        })
```

- [ ] **Step 2: Confirm RED**

Run: `python -m pytest tests/unit/test_canonical_hash.py tests/unit/test_claim_invariants.py tests/unit/test_evidence_reference.py tests/unit/test_prediction_result.py -q`

Expected: FAIL on missing `src.domain` models and helpers.

- [ ] **Step 3: Implement the exact shared primitives**

```python
# src/domain/hashing.py
from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import json
from typing import Any


def canonical_bytes(value: Any, exclude: frozenset[str] = frozenset()) -> bytes:
    raw = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    if isinstance(raw, Mapping):
        raw = {key: item for key, item in raw.items() if key not in exclude}
    return json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def content_hash(value: Any, exclude: frozenset[str] = frozenset()) -> str:
    return hashlib.sha256(canonical_bytes(value, exclude)).hexdigest()


def utc_now() -> datetime:
    return datetime.now(UTC)
```

Implement models as strict Pydantic v2 discriminated unions with `ConfigDict(extra="forbid")`, exact literals/limits from design section 4, serializers emitting UTC `Z`, and model validators enforcing verdict, label, severity, classification, event-chain, risk-reference, and error-analysis invariants. Put enum values in the design’s fixed serialized order.

- [ ] **Step 4: Run focused tests, refactor duplicate validators into named helpers, rerun**

Run: `python -m pytest tests/unit/test_canonical_hash.py tests/unit/test_claim_invariants.py tests/unit/test_evidence_reference.py tests/unit/test_prediction_result.py -q`

Expected: PASS, including illegal C0, length, duplicate-label, invalid-offset, invalid-verdict, and success/failure union cases.

- [ ] **Step 5: Request approval and commit**

```powershell
git add src/domain tests/unit/test_canonical_hash.py tests/unit/test_claim_invariants.py tests/unit/test_evidence_reference.py tests/unit/test_prediction_result.py
git commit -m "feat: define immutable domain contracts and canonical hashes"
```

