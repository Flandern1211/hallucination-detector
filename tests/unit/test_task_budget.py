from threading import Event, Thread

import pytest

from src.domain.models import ProviderUsage
from src.providers.budget import (
    RequestBudgetExhausted,
    TaskBudget,
    TaskCancelled,
    TaskDeadlineExceeded,
    TokenBudgetExhausted,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_request_budget_never_permits_attempt_201() -> None:
    budget = TaskBudget(200, 250_000, 1800, FakeClock(), Event())
    for _ in range(200):
        budget.before_request()

    with pytest.raises(RequestBudgetExhausted):
        budget.before_request()


def test_token_breaker_allows_only_last_response_to_cross_limit() -> None:
    budget = TaskBudget(200, 250_000, 1800, FakeClock(), Event())
    budget.record_usage(
        ProviderUsage(prompt_tokens=249_999, completion_tokens=2, total_tokens=250_001)
    )

    with pytest.raises(TokenBudgetExhausted):
        budget.before_request()


def test_cancel_and_monotonic_deadline_stop_before_transport() -> None:
    clock, cancelled = FakeClock(), Event()
    budget = TaskBudget(8, 50_000, 300, clock, cancelled)
    cancelled.set()
    with pytest.raises(TaskCancelled):
        budget.before_request()

    other = TaskBudget(8, 50_000, 300, clock, Event())
    clock.now = 300.0
    with pytest.raises(TaskDeadlineExceeded):
        other.before_request()


def test_request_budget_is_thread_safe() -> None:
    budget = TaskBudget(200, 250_000, 1800, FakeClock(), Event())
    permitted: list[bool] = []

    def attempt() -> None:
        try:
            budget.before_request()
        except RequestBudgetExhausted:
            return
        permitted.append(True)

    threads = [Thread(target=attempt) for _ in range(220)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(permitted) == 200
    assert budget.network_attempt_count == 200
