from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event, RLock
from typing import Any


class ExecutorBusy(RuntimeError):
    pass


class InProcessExecutor:
    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._lock = RLock()
        self._run_id: str | None = None
        self._cancel_event: Event | None = None
        self._future: Future[Any] | None = None

    def submit(self, run_id: str, task: Callable[[Event], Any]) -> Future[Any]:
        with self._lock:
            if self._future is not None and not self._future.done():
                raise ExecutorBusy(f"executor is already running {self._run_id!r}")
            cancel_event = Event()
            future = self._pool.submit(task, cancel_event)
            self._run_id = run_id
            self._cancel_event = cancel_event
            self._future = future
            future.add_done_callback(self._clear_if_current)
            return future

    def _clear_if_current(self, future: Future[Any]) -> None:
        with self._lock:
            if self._future is future:
                self._run_id = None
                self._cancel_event = None
                self._future = None

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            if self._run_id != run_id or self._future is None or self._future.done():
                return False
            if self._cancel_event is not None:
                self._cancel_event.set()
            return True

    def is_busy(self) -> bool:
        with self._lock:
            return self._future is not None and not self._future.done()

    def shutdown(self) -> None:
        with self._lock:
            if self._cancel_event is not None:
                self._cancel_event.set()
        self._pool.shutdown(wait=True)
