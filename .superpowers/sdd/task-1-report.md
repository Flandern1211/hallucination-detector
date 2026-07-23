# Task 1 Reconciliation Report

## Scope

Audited the existing Task 1 scaffold from commit `4e016ef` and reconciled the two
pending packaging edits. Protected benchmark and design inputs were not modified.

## Result

The package skeleton, resource files, local pinned vendor assets, licenses, and
hash manifest match the task brief. The pending `pyproject.toml` changes correctly
limit API package data to vendor assets and exclude discovered bytecode from wheels.

One concrete gap was found during the first distribution build: the source
distribution still contained
`src/api/static/__pycache__/__init__.cpython-311.pyc`. `exclude-package-data`
affects wheel contents, but source distributions use the egg-info source manifest.
Added `MANIFEST.in` with `global-exclude *.py[cod]` and a regression test for the
source-distribution manifest. The test was observed failing before that file
existed, then passing after it was added.

## Files changed for Task 1

- `MANIFEST.in` — exclude generated Python bytecode from source distributions.
- `pyproject.toml` — retain the pending wheel package-data/bytecode exclusions.
- `tests/unit/test_packaging_config.py` — retain config coverage and add the
  source-distribution bytecode exclusion regression test.

## Commands and outputs

| Command | Latest result |
| --- | --- |
| `python -m pytest tests/unit/test_packaging_config.py tests/unit/test_read_only_resources.py -q` (before fix) | `4 passed in 0.07s` |
| `python -m pytest tests/unit/test_packaging_config.py -q` (RED) | `1 failed, 2 passed`; failed with `FileNotFoundError: MANIFEST.in` |
| `python -m pytest tests/unit/test_packaging_config.py tests/unit/test_read_only_resources.py -q` (after fix) | `5 passed, 1 warning in 0.10s`; warning was pytest unable to write its ignored cache due sandbox permissions |
| `python -m pytest -q` | `4 passed in 0.08s` before the new regression test was added |
| `python -m ruff check .` | `All checks passed!` before the new regression test was added |
| `python -m ruff format --check .` | `16 files already formatted` before the new regression test was added |
| `python -m mypy src tests` | `Success: no issues found in 16 source files` before the new regression test was added |
| `python -m build` (initial) | Failed only because the sandbox blocked PyPI access for isolated `setuptools>=75` installation; build output also exposed the sdist `.pyc` pollution |
| `python -m build` (approved rerun, before fix) | Built wheel/sdist, but sdist included `src/api/static/__pycache__/__init__.cpython-311.pyc` and emitted the related setuptools warning |
| `python -m build` (approved rerun, after fix) | Exit 0; built both artifacts, with no bytecode copied into sdist or wheel |
| `git diff --check` | Exit 0 |

## Self-review

- The newly added manifest rule is the smallest source-distribution-only change;
  it does not alter runtime behavior or public data contracts.
- The package-data scope remains limited to the vendored static assets, templates,
  and declared JSON resources.
- No local CDN dependency or external LLM call was introduced.
- The local build still emits setuptools' non-blocking missing-README warning. A
  README is outside this Task 1 brief and was not added.

## Concerns

The final focused pytest run emitted a sandbox filesystem warning when trying to
write `.pytest_cache`; all five tests passed. The build had no bytecode-pollution
warning after the manifest fix.

## Review finding fix: complete static package-data scope

### Finding and correction

The prior reconciliation narrowed `src.api` package data from `static/**/*` to
`static/vendor/**/*`. That would omit planned first-party assets such as
`static/css/app.css` and `static/js/app.js` from built distributions. The task
brief requires the broader `static/**/*` pattern, so it has been restored while
retaining the existing package-discovery, wheel package-data, and sdist bytecode
exclusions.

### TDD evidence

1. Updated `test_package_data_excludes_python_bytecode` to expect `static/**/*`.
2. Ran `python -m pytest tests/unit/test_packaging_config.py -q` before changing
   the configuration: `1 failed, 2 passed`; the expected mismatch was
   `static/vendor/**/*` versus `static/**/*`.
3. Changed only the `src.api` package-data entry in `pyproject.toml`.
4. Ran the requested focused verification:

| Command | Result |
| --- | --- |
| `python -m pytest tests/unit/test_packaging_config.py tests/unit/test_read_only_resources.py -q` | `5 passed in 0.09s` |
| `python -m ruff check tests/unit/test_packaging_config.py` | `All checks passed!` |
| `python -m ruff format --check tests/unit/test_packaging_config.py` | `1 file already formatted` |
| `python -m mypy tests/unit/test_packaging_config.py` | `Success: no issues found in 1 source file` |
| `python -m build` | exit 0; wheel and sdist built successfully |
| Archive listing check (`tar` for sdist and `zipfile` for wheel) | `No bytecode found in wheel or sdist.` |

The build reports only the pre-existing non-blocking missing-README warning and
`MANIFEST.in` notices that no matching bytecode is included.

### Explicit deferral

Wheel installation in an isolated environment and a built-artifact integration
test are intentionally not added in this Task 1 review fix. The approved plan
assigns `tests/integration/test_built_artifact.py` and isolated installed-artifact
verification to Task 14. This fix preserves Task 1's focused configuration,
resource, and archive-content verification without pre-empting that task.
