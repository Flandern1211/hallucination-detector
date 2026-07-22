from threading import Event

import pytest

from src.infrastructure.in_process_executor import ExecutorBusy, InProcessExecutor


def test_executor_rejects_second_task_and_cooperatively_cancels() -> None:
    started = Event()
    stopped = Event()
    executor = InProcessExecutor()

    def task(cancel_event: Event) -> None:
        started.set()
        cancel_event.wait(2)
        stopped.set()

    future = executor.submit("run-1", task)
    assert started.wait(1)
    with pytest.raises(ExecutorBusy):
        executor.submit("run-2", task)
    assert executor.cancel("run-1") is True
    future.result(timeout=2)
    assert stopped.is_set()
    assert executor.is_busy() is False
    executor.shutdown()
