# Tasks 4–5 Batch Report

## Task 4 — Detection pipeline

- RED: focused collection failed as expected because
  `src.detection.aggregator` and `src.detection.orchestrator` did not exist.
- GREEN: `python -m pytest tests/unit/test_aggregation.py
  tests/unit/test_detection_orchestrator.py
  tests/isolation/test_detection_label_isolation.py -q` → `9 passed in 1.61s`.
- Changed-files Ruff lint: passed.
- Changed-files Ruff format check: 11 files already formatted.
- Changed-files mypy: passed with no issues in 11 files.

Implemented stable aggregation, sequential three-stage orchestration, local claim and
evidence slice validation, application-assigned stable claim IDs, per-record failure
isolation, input-order preservation, progress events, label-source isolation, shared
request/token/deadline/cancellation budget primitives, and true returned attempt/usage
aggregation.

## Task 5 — OpenAI-compatible Provider

- RED: focused collection failed as expected because
  `src.providers.llm_provider` did not exist.
- GREEN: `python -m pytest tests/contract/test_llm_provider.py
  tests/unit/test_task_budget.py -q` → `31 passed in 1.00s`.
- Changed-files Ruff lint: passed.
- Changed-files Ruff format check: 5 files already formatted.
- Changed-files mypy: **not yet green**. Latest run reported three annotation-only
  diagnostics: one widened `error_code: str` in `llm_provider.py`, and two overly
  narrow inferred dictionary value types in `test_llm_provider.py`.

Implemented the standard-library urllib transport and replaceable transport protocol,
the three approved environment variables, HTTPS with loopback-only HTTP exceptions,
60-second/2-MiB bounds, fixed structured-output operations, explicit
`UNTRUSTED_DATA` messages, retry/backoff/Retry-After behavior, one non-retrying shape
repair, strict typed output models, task model binding, usage enforcement, context
rejection, and sanitized local errors. All automated Provider tests use scripted
transports and open no network connection.

## Handoff

No full suite or build was run, per acceleration instructions. No commit was created.
Protected inputs and approved documents were not modified. Implementation test and
Ruff evidence is green; the three Task 5 mypy annotations above remain for the batch
owner to fix before claiming complete static verification.
