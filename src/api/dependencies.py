from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
import os
from pathlib import Path
from typing import Any, cast

from src.application.detection_service import DetectionService
from src.application.evaluation_service import EvaluationService
from src.application.review_service import ReviewService
from src.application.reporting_service import ReportingService
from src.application.suggestion_service import SuggestionService
from src.application.run_service import RunService
from src.detection.orchestrator import DetectionOrchestrator
from src.detection.mock_engine import MockDetectionEngine
from src.domain.models import BaselineDetectorConfig
from src.infrastructure.artifact_store import ArtifactStore
from src.infrastructure.in_process_executor import InProcessExecutor
from src.infrastructure.run_registry import RunRegistry
from src.review.revision_store import RevisionStore
from src.providers.llm_provider import LLMProvider, ProviderConfig
from src.evaluation.type_mapping import load_type_compatibility


@dataclass(slots=True)
class ApplicationContainer:
    run_service: object | None = None
    review_service: object | None = None
    evaluation_service: object | None = None
    suggestion_service: object | None = None
    reporting_service: object | None = None
    artifact_store: ArtifactStore | None = None
    detector_config: BaselineDetectorConfig | None = None


def default_container() -> ApplicationContainer:
    registry = RunRegistry()
    detector = BaselineDetectorConfig.model_validate_json(
        files("src.resources").joinpath("detectors/baseline.json").read_text("utf-8")
    )
    # Use the same environment configuration validated by RunService at run creation.
    # Keep startup available without configuration; creation then returns a clear error.
    try:
        config = ProviderConfig.from_environment(os.environ)
    except Exception:
        config = ProviderConfig(
            api_key="startup-placeholder",
            base_url="http://127.0.0.1:9",
            model="unconfigured",
        )
    provider = LLMProvider(config)
    engine = (
        MockDetectionEngine() if config.model.lower() == "mock" else DetectionOrchestrator(provider)
    )
    artifact_store = ArtifactStore(Path(".runtime"))
    detection = DetectionService(registry, engine, detector, artifact_store=artifact_store)
    run_service = RunService(registry, detection, InProcessExecutor(), detector=detector)
    evaluation = EvaluationService(
        registry, load_type_compatibility(), artifact_store=artifact_store
    )
    review = ReviewService(registry, RevisionStore(), artifact_store=artifact_store)

    def resolve_label_source(run_id: str, source: str):  # type: ignore[no-untyped-def]
        if source == "official_ground_truth":
            return evaluation.official_source(run_id)
        return review.human_source(run_id)

    suggestion = SuggestionService(
        registry=cast(Any, registry),
        provider=engine if isinstance(engine, MockDetectionEngine) else provider,
        detector=detector,
        label_source_resolver=resolve_label_source,
        artifact_store=artifact_store,
    )
    return ApplicationContainer(
        run_service=run_service,
        review_service=review,
        evaluation_service=evaluation,
        suggestion_service=suggestion,
        reporting_service=ReportingService(),
        artifact_store=artifact_store,
        detector_config=detector,
    )
