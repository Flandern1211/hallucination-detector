from collections.abc import Callable
from threading import Event, Lock

from src.domain.models import ProviderUsage


class BudgetStop(RuntimeError):
    error_code: str


class TaskCancelled(BudgetStop):
    error_code = "cancelled"


class TaskDeadlineExceeded(BudgetStop):
    error_code = "run_deadline_exceeded"


class RequestBudgetExhausted(BudgetStop):
    error_code = "request_budget_exhausted"


class TokenBudgetExhausted(BudgetStop):
    error_code = "token_budget_exhausted"


class TaskBudget:
    def __init__(
        self,
        request_limit: int,
        token_limit: int,
        deadline_seconds: float,
        clock: Callable[[], float],
        cancel_event: Event,
    ) -> None:
        if request_limit <= 0 or token_limit <= 0 or deadline_seconds <= 0:
            raise ValueError("budget limits and deadline must be positive")
        self.request_limit = request_limit
        self.token_limit = token_limit
        self.deadline_seconds = deadline_seconds
        self.clock = clock
        self.cancel_event = cancel_event
        self.started_at = clock()
        self.network_attempt_count = 0
        self.usage = ProviderUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        self._lock = Lock()

    def before_request(self) -> None:
        with self._lock:
            if self.cancel_event.is_set():
                raise TaskCancelled
            if self.clock() >= self.started_at + self.deadline_seconds:
                raise TaskDeadlineExceeded
            if self.usage.total_tokens >= self.token_limit:
                raise TokenBudgetExhausted
            if self.network_attempt_count >= self.request_limit:
                raise RequestBudgetExhausted
            self.network_attempt_count += 1

    def record_usage(self, usage: ProviderUsage) -> None:
        with self._lock:
            self.usage = ProviderUsage(
                prompt_tokens=self.usage.prompt_tokens + usage.prompt_tokens,
                completion_tokens=self.usage.completion_tokens + usage.completion_tokens,
                total_tokens=self.usage.total_tokens + usage.total_tokens,
            )
