"""HTTP-independent request, response, and error types for detection runs."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.domain.enums import RunState
from src.domain.models import DetectionRunConfig


class ProviderConfigurationUnavailable(RuntimeError):
    """Raised before a run is created when required provider settings are absent."""


class ExecutorUnavailable(RuntimeError):
    """Raised when the single in-process worker is already occupied."""


class RunPersistenceError(RuntimeError):
    """Records that an in-memory terminal run could not be persisted."""


class RunNotRetryable(RuntimeError):
    """Raised when retry is requested for a run without retryable failures."""


class RunNotFreezable(RuntimeError):
    """Raised when an explicit freeze is requested outside the partial state."""


@dataclass(frozen=True, slots=True)
class CreateRunRequest:
    config: DetectionRunConfig = field(
        default_factory=lambda: DetectionRunConfig(
            detector_version="baseline-v1", external_processing_acknowledged=True
        )
    )


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: str
    state: RunState
    warnings: tuple[str, ...]
    parent_run_id: str | None = None


@dataclass(frozen=True, slots=True)
class RunProgress:
    id: str
    state: RunState
    total_count: int
    completed_count: int
    success_count: int
    failure_count: int
    warnings: tuple[str, ...]
    persisted: bool
    persistence_error: str | None
    parent_run_id: str | None
