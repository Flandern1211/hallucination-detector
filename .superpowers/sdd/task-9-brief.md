### Task 9: Error Analysis and Constrained Experimental Suggestions

**Files:**
- Create: `src/suggestions/error_analyzer.py`
- Create: `src/suggestions/suggestion_generator.py`
- Create: `src/suggestions/validator.py`
- Create: `src/application/suggestion_service.py`
- Create: `tests/unit/test_error_analysis.py`
- Create: `tests/unit/test_suggestion_validator.py`
- Extend: `tests/isolation/test_detection_label_isolation.py`

**Interfaces:**
- Produces: `build_cases(run, label_source) -> SuggestionCases`; `validate_analyses(expected_cases, analyses)`; `validate_suggestions(suggestions, source_texts, source_ids)`; `SuggestionService.start(run_id, SuggestionRequest) -> SuggestionTaskSummary`.
- Consumes: frozen run, explicit single source literal `official_ground_truth | human_revision`, full official evaluation or 100%-covered review snapshot, `SuggestionInferenceProvider`, 8-request/50,000-token/300-second budget.

- [ ] **Step 1: Write failing eligibility, analysis, and whitelist tests**

```python
def test_case_refs_follow_prediction_order_and_hide_record_ids() -> None:
    cases = build_cases(frozen_run_with_fp_fn(), OfficialSource(official_labels()))
    assert [case.case_ref for case in cases.items] == ["case-001", "case-002"]
    provider_payload = cases.provider_payload()
    assert "h03" not in json.dumps(provider_payload, ensure_ascii=False)
    assert cases.record_id_by_case_ref == {"case-001": "h03", "case-002": "h11"}


def test_analysis_must_match_case_set_order_and_error_kind() -> None:
    expected = [case("case-001", "false_negative"), case("case-002", "false_positive")]
    with pytest.raises(InvalidErrorAnalysis):
        validate_analyses(expected, [analysis("case-002", "false_positive")])


@pytest.mark.parametrize("proposed_change", [
    "当置信度低于0.7时通过", "执行 `open('x').write(y)`", "请求 https://example.com",
    "修改 src/resources/detectors/baseline.json", "{{ user_question }}",
])
def test_rejects_threshold_code_network_path_and_template_payloads(proposed_change: str) -> None:
    with pytest.raises(UnsafeSuggestion):
        validate_suggestions([suggestion(proposed_change)], ["source material"], {"h01"})


def test_rejects_sample_id_and_32_normalized_source_characters() -> None:
    source = "ＡＢＣ   " + "很长的客户原文" * 6
    with pytest.raises(UnsafeSuggestion):
        validate_suggestions([suggestion("h01 " + normalize(source)[:32])], [source], {"h01"})
```

Also test source conflicts, manual-review coverage under 100%, stale prediction hashes, no FN/FP returning 409 without provider calls, duplicate/missing/extra cases, nine reason enums, non-empty 4,000-character fields, at most 20 suggestions, 10 known risks, banned effectiveness terms, failed analysis stopping generation, cancellation/deadline/no-partial-report behavior, and a second report returning 409.

- [ ] **Step 2: Confirm RED**

Run: `python -m pytest tests/unit/test_error_analysis.py tests/unit/test_suggestion_validator.py tests/isolation/test_detection_label_isolation.py -q`

Expected: FAIL because suggestion modules do not exist.

- [ ] **Step 3: Implement normalized-memory and payload validators**

```python
def normalize_for_memory_check(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).lower().split())


def contains_source_memory(candidate: str, sources: list[str], window: int = 32) -> bool:
    normalized_candidate = normalize_for_memory_check(candidate)
    for source in sources:
        normalized_source = normalize_for_memory_check(source)
        for start in range(max(0, len(normalized_source) - window + 1)):
            if normalized_source[start:start + window] in normalized_candidate:
                return True
    return False
```

Add conservative token/AST-free lexical checks for decimal thresholds, fenced or inline code, template markers, shell verbs, URL schemes, path mutations, dependency/source/config/provider/contract mutation instructions, sample IDs, and the five forbidden English effectiveness phrases. Reject the whole report on any violation; never silently redact or partially save it.

- [ ] **Step 4: Implement the two-call suggestion service**

Require a newly acknowledged external-processing flag. The first call receives `case_ref` plus delimited untrusted source material and selected labels; its output must exactly match every case. The second receives only validated successful analyses plus baseline metadata/source name—not questions, replies, knowledge base, IDs, or the local mapping. Bind server-generated suggestion UUIDs, actual model, hashes, timestamp, coverage, and warning `小样本实验性建议，不代表效果提升` after validation.

- [ ] **Step 5: Verify isolation and budgets**

Run: `python -m pytest tests/unit/test_error_analysis.py tests/unit/test_suggestion_validator.py tests/unit/test_task_budget.py tests/isolation/test_detection_label_isolation.py -q`

Expected: PASS; no-error requests make zero provider calls, invalid/partial tasks save no `SuggestionReport`, and baseline/resource hashes remain unchanged.

- [ ] **Step 6: Request approval and commit**

```powershell
git add src/suggestions src/application/suggestion_service.py tests/unit/test_error_analysis.py tests/unit/test_suggestion_validator.py tests/isolation/test_detection_label_isolation.py
git commit -m "feat: generate isolated experimental suggestions"
```

