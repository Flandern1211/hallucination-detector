from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from src.domain.hashing import utc_now
from src.domain.models import BaselineDetectorConfig, ExperimentalSuggestion, SuggestionReport
from src.infrastructure.artifact_store import ArtifactStore
from src.providers.base import ProviderFailure, SuggestionInferenceProvider
from src.providers.budget import TaskBudget
from src.providers.budget import BudgetStop
from src.suggestions.error_analyzer import (
    HumanRevisionSource,
    InvalidErrorAnalysis,
    OfficialSource,
    SuggestionRun,
    build_cases,
    validate_analyses,
)
from src.suggestions.validator import validate_suggestions
from src.reporting.exporter import export_suggestions
from threading import Event
import time


class NoAnalyzableErrors(RuntimeError):
    pass


class SuggestionConflict(RuntimeError):
    pass


class SuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    label_source: Literal["official_ground_truth", "human_revision"]
    external_processing_acknowledged: Literal[True]


@dataclass(frozen=True, slots=True)
class SuggestionTaskSummary:
    run_id: str
    status: Literal["completed", "failed"]


class SuggestionRunRegistry(Protocol):
    def get(self, run_id: str) -> SuggestionRun: ...


class SuggestionService:
    def __init__(
        self,
        *,
        registry: SuggestionRunRegistry,
        provider: SuggestionInferenceProvider,
        detector: BaselineDetectorConfig,
        label_source_resolver: Callable[
            [str, Literal["official_ground_truth", "human_revision"]],
            OfficialSource | HumanRevisionSource,
        ],
        artifact_store: ArtifactStore,
        uuid_factory: Callable[[], object] = lambda: "suggestion-1",
        wall_clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._registry = registry
        self._provider = provider
        self._detector = detector
        self._label_source_resolver = label_source_resolver
        self._artifact_store = artifact_store
        self._uuid_factory = uuid_factory
        self._clock = wall_clock
        self._reports: dict[str, SuggestionReport] = {}

    def start(self, run_id: str, request: SuggestionRequest) -> SuggestionTaskSummary:
        if (
            run_id in self._reports
            or self._artifact_store.export_path(
                run_id, "suggestions/suggestion_report.json"
            ).exists()
        ):
            raise SuggestionConflict(run_id)
        run = self._registry.get(run_id)
        label_source = self._label_source_resolver(run_id, request.label_source)
        cases = build_cases(run, label_source)
        if not cases.items:
            raise NoAnalyzableErrors(run_id)
        budget = TaskBudget(
            request_limit=8,
            token_limit=50_000,
            deadline_seconds=300,
            clock=time.monotonic,
            cancel_event=Event(),
        )
        try:
            analysis_result = self._provider.analyze_errors(
                list(cases.items), self._detector, budget
            )
            analyses = validate_analyses(cases.items, analysis_result.value)
            suggestion_result = self._provider.generate_suggestions(
                list(analyses), self._detector, request.label_source, budget
            )
            source_texts = [
                text
                for case in cases.items
                for text in (case.user_question, case.system_reply, case.knowledge_base)
            ]
            bodies = validate_suggestions(
                list(suggestion_result.value),
                source_texts,
                set(cases.record_id_by_case_ref.values()),
            )
        except (BudgetStop, ProviderFailure, InvalidErrorAnalysis, ValueError):
            return SuggestionTaskSummary(run_id, "failed")
        suggestions = [
            ExperimentalSuggestion(
                suggestion_id=str(self._uuid_factory()),
                category=body.category,
                target_stage=body.target_stage,
                rationale=body.rationale,
                proposed_change=body.proposed_change,
                known_risks=list(body.known_risks),
            )
            for body in bodies
        ]
        report = SuggestionReport(
            schema_version="1.0",
            run_id=run_id,
            label_source=request.label_source,
            input_hash=run.input_hash,
            prediction_hash=run.prediction_hash,
            detector_version="baseline-v1",
            detector_config_hash=run.detector_config_hash,
            model_name=suggestion_result.model_name,
            generated_at_utc=self._clock(),
            coverage=1.0,
            warning="小样本实验性建议，不代表效果提升",
            analyses=list(analyses),
            suggestions=suggestions,
        )
        self._artifact_store.write_json(
            run_id, "suggestions/suggestion_report.json", report.model_dump(mode="json")
        )
        self._artifact_store.write_json(
            run_id,
            "suggestions.json",
            export_suggestions(report.model_dump(mode="json")),
        )
        self._reports[run_id] = report
        return SuggestionTaskSummary(run_id, "completed")

    def get_report(self, run_id: str) -> SuggestionReport:
        return self._reports[run_id]
