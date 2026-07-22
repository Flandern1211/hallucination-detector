import json
from importlib.resources import files
from typing import Any

from src.detection.orchestrator import DetectionOrchestrator
from src.domain.models import (
    BaselineDetectorConfig,
    Claim,
    ClaimJudgement,
    ProviderUsage,
    ReplyRecord,
    SuccessfulPrediction,
)
from src.application.review_service import ReviewSaveRequest, ReviewService
from src.domain.enums import RunState
from src.domain.hashing import content_hash
from src.domain.models import ClassificationResult, DetectionRunConfig
from src.infrastructure.run_registry import RunRegistry
from src.providers.base import ProviderCallResult
from src.providers.budget import TaskBudget
from src.review.revision_store import RevisionStore


class CapturingDetectionProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def extract_claims(
        self, record: ReplyRecord, detector: BaselineDetectorConfig, budget: TaskBudget
    ) -> ProviderCallResult[list[Claim]]:
        self.calls.append({"record": record.model_dump(), "detector": detector.model_dump()})
        return ProviderCallResult(
            [],
            "model",
            ProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            1,
            False,
        )

    def judge_claim(
        self,
        record: ReplyRecord,
        claim: Claim,
        detector: BaselineDetectorConfig,
        budget: TaskBudget,
    ) -> ProviderCallResult[ClaimJudgement]:
        raise AssertionError("empty extraction must not call judgement")

    def find_omissions(
        self, record: ReplyRecord, detector: BaselineDetectorConfig, budget: TaskBudget
    ) -> ProviderCallResult[list[Any]]:
        self.calls.append({"record": record.model_dump(), "detector": detector.model_dump()})
        return ProviderCallResult(
            [],
            "model",
            ProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            1,
            False,
        )


def test_detection_provider_payload_never_contains_label_sources() -> None:
    provider = CapturingDetectionProvider()
    record = ReplyRecord(
        id="h01",
        user_question="问题",
        system_reply="回复",
        knowledge_base="知识库",
    )
    detector = BaselineDetectorConfig.model_validate_json(
        files("src.resources").joinpath("detectors/baseline.json").read_text("utf-8")
    )

    DetectionOrchestrator(provider).detect_batch([record], detector)

    serialized = json.dumps(provider.calls, ensure_ascii=False)
    assert "official_ground_truth" not in serialized
    assert "human_revision" not in serialized
    assert "risk_reference" not in serialized


def test_review_operation_cannot_mutate_frozen_predictions() -> None:
    registry = RunRegistry(uuid_factory=lambda: "run-review")
    record = ReplyRecord(id="h01", user_question="问题", system_reply="回复", knowledge_base="")
    result = ClassificationResult(
        is_hallucination=False,
        labels=[],
        primary_type=None,
        severity=None,
        review_required=True,
        claims=[],
        omissions=[],
        summary="正常",
    )
    prediction = SuccessfulPrediction(
        kind="success",
        id="h01",
        result=result,
        engine="llm",
        model_name="model",
        detector_version="baseline-v1",
        config_hash="b" * 64,
        attempt_count=1,
    )
    run = registry.create(
        records=[record],
        config=DetectionRunConfig(
            detector_version="baseline-v1",
            manual_review_enabled=True,
            external_processing_acknowledged=True,
        ),
        input_hash="a" * 64,
        detector_config_hash="b" * 64,
        provider_model="model",
    )
    registry.transition(run.id, RunState.running)
    registry.set_predictions(run.id, [prediction])
    registry.transition(run.id, RunState.frozen)
    before = run.prediction_hash

    ReviewService(registry, RevisionStore()).save(
        run.id,
        "h01",
        ReviewSaveRequest(
            status="confirmed_correct",
            save_request_id="save-1",
            source_prediction_hash=content_hash(prediction),
            reviewed_result=result,
        ),
    )

    assert run.prediction_hash == before
