# Task 3 Report: Reply and Ground-Truth Input Validation

## Scope

Created only the Task 3 implementation and focused tests:

- `src/input/loader.py`
- `src/input/validator.py`
- `tests/unit/test_input_validation.py`
- `tests/unit/test_ground_truth_validation.py`

The benchmark files were loaded only from bytes. Both tests assert that their bytes are unchanged after loading.

## RED

Command:

```text
python -m pytest tests/unit/test_input_validation.py tests/unit/test_ground_truth_validation.py -q
```

Result: expected collection failure because `src.input.loader` did not yet exist.

## GREEN and focused verification

Commands and latest results:

```text
python -m pytest tests/unit/test_input_validation.py tests/unit/test_ground_truth_validation.py -q
18 passed in 0.50s

python -m ruff check src/input/loader.py src/input/validator.py tests/unit/test_input_validation.py tests/unit/test_ground_truth_validation.py
All checks passed!

python -m ruff format --check src/input/loader.py src/input/validator.py tests/unit/test_input_validation.py tests/unit/test_ground_truth_validation.py
4 files already formatted

python -m mypy src/input/loader.py src/input/validator.py tests/unit/test_input_validation.py tests/unit/test_ground_truth_validation.py
Success: no issues found in 4 source files
```

## Coverage

- Reply and ground-truth JSON parsing, strict model validation, stable field paths, duplicate normalized IDs, C0 controls, and forbidden extra fields.
- 5 MiB body limit; one-to-twenty record bounds; reply total-text limit of 200,000 characters.
- Ground-truth normal/positive label invariants and 10,000-character detail boundary.
- Reply hash is canonical across JSON key order and changes with input order.
