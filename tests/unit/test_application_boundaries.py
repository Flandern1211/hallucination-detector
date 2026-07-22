from pathlib import Path

from src.application.models import ExecutorUnavailable, RunPersistenceError
from src.infrastructure.in_process_executor import ExecutorBusy


def test_application_modules_do_not_import_fastapi() -> None:
    for path in Path("src/application").glob("*.py"):
        assert "fastapi" not in path.read_text(encoding="utf-8").lower()


def test_application_errors_are_http_independent() -> None:
    assert issubclass(ExecutorUnavailable, RuntimeError)
    assert issubclass(RunPersistenceError, RuntimeError)
    assert issubclass(ExecutorBusy, RuntimeError)
