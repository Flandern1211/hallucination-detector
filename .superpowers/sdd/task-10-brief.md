### Task 10: Safe JSON and Markdown Exports

**Files:**
- Create: `src/reporting/exporter.py`
- Create: `src/application/reporting_service.py`
- Create: `tests/unit/test_exporter.py`

**Interfaces:**
- Produces: `export_predictions`, `export_evaluation`, `export_feedback`, `export_suggestions`, `render_markdown_report`; artifact allowlist mapping `predictions.json`, `evaluation.json`, `feedback.json`, `suggestions.json`, `report.md` to validated runtime sources.
- Consumes: immutable run snapshot and independently typed derived artifacts; artifact store.

- [ ] **Step 1: Write failing export and Markdown-injection tests**

```python
def test_exports_mark_sources_and_contract_version() -> None:
    exports = build_all_exports(complete_run())
    assert exports.predictions["schema_version"] == "1.0"
    assert exports.predictions["source"] == "model_prediction"
    assert exports.evaluation["source"] == "official_ground_truth"
    assert exports.feedback["source"] == "human_revision"
    assert exports.suggestions["source"] == "experimental_suggestion"


def test_markdown_uses_longer_fence_and_never_emits_raw_html() -> None:
    report = render_markdown_report(run_with_user_text("</script> ``` <img src=x onerror=1>"))
    assert "<img" not in report and "</script>" not in report
    assert "````text" in report


@pytest.mark.parametrize("term", [
    "validated", "improved", "upgrade", "out-of-fold", "full-data replay",
])
def test_report_never_describes_suggestions_with_forbidden_terms(term: str) -> None:
    assert term not in render_markdown_report(complete_run()).lower()
```

- [ ] **Step 2: Confirm RED**

Run: `python -m pytest tests/unit/test_exporter.py -q`

Expected: FAIL because exporter modules are missing.

- [ ] **Step 3: Implement source-marked exports and dynamic fences**

```python
def markdown_fence(value: str) -> str:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", value)), default=0)
    fence = "`" * max(3, longest + 1)
    escaped = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"{fence}text\n{escaped}\n{fence}"
```

The Markdown report must contain classification definitions, three-stage method, coverage and metric denominators, all failures, FN/FP detail, review summary, error analyses, experimental suggestions with fixed warning, limitations (20 records/2 normal records/closed-world/no production generalization), actual model/config/attempt metadata, and AI-tool usage. Label only the frozen prediction evaluation as `baseline`; do not emit unavailable sections as invented results.

- [ ] **Step 4: Verify all artifacts and corruption handling**

Run: `python -m pytest tests/unit/test_exporter.py tests/unit/test_artifact_store.py -q`

Expected: PASS; export hashes exclude their own `artifact_hash`, source types remain separate, and corrupted prerequisites are rejected.

- [ ] **Step 5: Request approval and commit**

```powershell
git add src/reporting src/application/reporting_service.py tests/unit/test_exporter.py
git commit -m "feat: export source-separated audit reports"
```

