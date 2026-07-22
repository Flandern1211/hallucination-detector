from __future__ import annotations

from collections.abc import Callable, Sequence

from src.domain.models import ExperimentalSuggestion, ExperimentalSuggestionBody


def bind_suggestion_ids(
    suggestions: Sequence[ExperimentalSuggestionBody],
    uuid_factory: Callable[[], object],
) -> tuple[ExperimentalSuggestion, ...]:
    return tuple(
        ExperimentalSuggestion(
            suggestion_id=str(uuid_factory()),
            category=suggestion.category,
            target_stage=suggestion.target_stage,
            rationale=suggestion.rationale,
            proposed_change=suggestion.proposed_change,
            known_risks=list(suggestion.known_risks),
        )
        for suggestion in suggestions
    )
