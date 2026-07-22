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
)
from src.providers.base import ProviderCallResult
from src.providers.budget import TaskBudget


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
