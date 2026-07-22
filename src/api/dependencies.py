from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ApplicationContainer:
    run_service: object | None = None
    review_service: object | None = None
    evaluation_service: object | None = None
    suggestion_service: object | None = None
    reporting_service: object | None = None


def default_container() -> ApplicationContainer:
    return ApplicationContainer()
