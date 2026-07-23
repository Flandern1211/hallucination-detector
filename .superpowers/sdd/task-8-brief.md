### Task 8: Official Evaluation, Risk Reference, and Metrics

**Files:**
- Create: `src/domain/metrics.py`
- Create: `src/evaluation/type_mapping.py`
- Create: `src/evaluation/evaluator.py`
- Create: `src/application/evaluation_service.py`
- Create: `tests/unit/test_metrics.py`
- Create: `tests/unit/test_risk_reference.py`
- Extend: `tests/isolation/test_detection_label_isolation.py`

**Interfaces:**
- Produces: `evaluate(predictions: list[PredictionResult], ground_truth: list[GroundTruthRecord], risk_reference: RiskReference | None, type_map: TypeCompatibility) -> EvaluationResult`; `EvaluationService.load_ground_truth(run_id: str, raw: bytes, request_id: str) -> GroundTruthSummary`; `EvaluationService.evaluate(run_id: str, request_id: str) -> EvaluationResult`; nullable `MetricValue(value: float | None, numerator: int, denominator: int, reason: str | None)`.
- Consumes: frozen predictions only, separately validated official labels, and evaluation-only resources.

- [ ] **Step 1: Write failing metric and alignment tests**

```python
def test_metrics_exclude_failures_and_report_all_id_sets() -> None:
    result = evaluate(
        predictions=[success("a", True, "知识冲突"), success("b", False), failure("c")],
        ground_truth=[truth("a", True, "政策编造"), truth("b", True, "信息遗漏"),
                      truth("c", False), truth("d", True, "安全误导")],
        risk_reference=None, type_map=type_map(),
    )
    assert (result.tp, result.fp, result.tn, result.fn) == (1, 0, 0, 1)
    assert result.failed_ids == ["c"]
    assert result.ground_truth_only_ids == ["d"]
    assert result.coverage.value == pytest.approx(0.5)
    assert result.complete is False


def test_zero_denominator_is_null_with_reason() -> None:
    result = evaluate([success("a", False)], [truth("a", False)], None, type_map())
    assert result.precision.value is None
    assert result.precision.reason == "no predicted positive records"


def test_partial_uploaded_severity_never_falls_back_to_benchmark() -> None:
    reference = choose_risk_reference(uploaded_truth_with_partial_severity(), benchmark_reference())
    assert reference is None
```

- [ ] **Step 2: Confirm RED**

Run: `python -m pytest tests/unit/test_metrics.py tests/unit/test_risk_reference.py tests/isolation/test_detection_label_isolation.py -q`

Expected: FAIL on missing evaluation modules.

- [ ] **Step 3: Implement exact formulae and type compatibility**

```python
def safe_ratio(numerator: int, denominator: int, reason: str) -> MetricValue:
    return MetricValue(value=None if denominator == 0 else numerator / denominator,
                       numerator=numerator, denominator=denominator,
                       reason=reason if denominator == 0 else None)


precision = safe_ratio(tp, tp + fp, "no predicted positive records")
recall = safe_ratio(tp, tp + fn, "no official positive records in evaluated intersection")
specificity = safe_ratio(tn, tn + fp, "no official normal records in evaluated intersection")
f1 = harmonic_mean(precision, recall)
macro_f1 = nullable_mean(positive_f1, negative_f1)
balanced_accuracy = nullable_mean(recall, specificity)
coverage = safe_ratio(len(successfully_matched_ids), len(ground_truth), "empty ground truth")
```

Primary-type denominator contains only dual-positive, dual-mappable records; unknown manual types stay in binary metrics and increment `unmappable_type_count`. High-risk recall is null unless a complete reference’s ground-truth hash matches exactly. Evaluation may persist normalized used fields and source hash but not original uploaded bytes.

`EvaluationService.load_ground_truth` first requires `RunState.FROZEN`. It stores at most one content hash per run: the identical hash/request replay is idempotent, while a different ground-truth hash returns a conflict and never replaces the first source.

- [ ] **Step 4: Verify metrics and frozen prediction isolation**

Run: `python -m pytest tests/unit/test_metrics.py tests/unit/test_risk_reference.py tests/isolation/test_detection_label_isolation.py -q`

Expected: PASS for TP/FP/TN/FN, precision/recall/F1/specificity/Macro-F1/balanced accuracy, type match, high-risk recall, coverage, differences, null denominators, and unchanged prediction hashes.

- [ ] **Step 5: Request approval and commit**

```powershell
git add src/domain/metrics.py src/evaluation src/application/evaluation_service.py tests/unit/test_metrics.py tests/unit/test_risk_reference.py tests/isolation/test_detection_label_isolation.py
git commit -m "feat: evaluate frozen predictions against official labels"
```

