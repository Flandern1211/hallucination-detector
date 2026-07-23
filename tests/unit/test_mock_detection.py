from importlib.resources import files
from pathlib import Path

from src.detection.mock_engine import MockDetectionEngine
from src.domain.models import (
    BaselineDetectorConfig,
    SuccessfulErrorAnalysis,
    SuccessfulPrediction,
)
from src.domain.models import ErrorAnalysisInput
from src.input.loader import load_reply_batch
from src.providers.budget import TaskBudget
from threading import Event


ROOT = Path(__file__).resolve().parents[2]


def test_mock_detection_is_deterministic_label_free_and_covers_full_input() -> None:
    records = load_reply_batch((ROOT / "task4_replies.json").read_bytes())
    detector = BaselineDetectorConfig.model_validate_json(
        files("src.resources").joinpath("detectors/baseline.json").read_text("utf-8")
    )

    first = MockDetectionEngine().detect_batch(records, detector)
    second = MockDetectionEngine().detect_batch(records, detector)

    assert first == second
    assert len(first.results) == 20
    assert all(isinstance(item, SuccessfulPrediction) for item in first.results)
    assert all(
        isinstance(item, SuccessfulPrediction) and item.result.is_hallucination
        for item in first.results
    )
    assert first.network_attempt_count == 20
    assert first.provider_usage.total_tokens == 0

    prediction = first.results[11]
    assert isinstance(prediction, SuccessfulPrediction)
    case = ErrorAnalysisInput(
        case_ref="case-001",
        error_kind="false_positive",
        user_question=records[11].user_question,
        system_reply=records[11].system_reply,
        knowledge_base=records[11].knowledge_base,
        prediction=prediction.result,
        expected_is_hallucination=False,
        expected_labels=[],
    )
    budget = TaskBudget(8, 50_000, 300, lambda: 0.0, Event())
    analyses = MockDetectionEngine().analyze_errors([case], detector, budget)
    successful_analyses = [
        item for item in analyses.value if isinstance(item, SuccessfulErrorAnalysis)
    ]
    suggestions = MockDetectionEngine().generate_suggestions(
        successful_analyses, detector, "official_ground_truth", budget
    )

    assert successful_analyses[0].primary_reason == "non_factual_expression_false_positive"
    assert suggestions.value[0].category == "label_boundary"
