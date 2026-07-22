import json
from importlib.resources import files
from pathlib import Path

import pytest

from src.application.detection_service import DetectionService
from src.application.models import CreateRunRequest, ProviderConfigurationUnavailable
from src.application.run_service import RunService
from src.domain.enums import RunState
from src.domain.hashing import content_hash
from src.domain.models import (
    BaselineDetectorConfig,
    BatchDetectionResult,
    ClassificationResult,
    FailedPrediction,
    ProviderUsage,
    PredictionResult,
    ReplyRecord,
    SuccessfulPrediction,
)
from src.infrastructure.artifact_store import ArtifactStore
from src.infrastructure.in_process_executor import InProcessExecutor
from src.infrastructure.run_registry import RunRegistry


def _detector_config() -> BaselineDetectorConfig:
    return BaselineDetectorConfig.model_validate_json(
        files("src.resources").joinpath("detectors/baseline.json").read_text("utf-8")
    )


def _environment() -> dict[str, str]:
    return {
        "HALLUCINATION_API_KEY": "secret",
        "HALLUCINATION_BASE_URL": "https://example.test",
        "HALLUCINATION_MODEL": "model-1",
    }


def _reply_bytes(ids: list[str], empty_knowledge_base: bool = False) -> bytes:
    return json.dumps(
        [
            {
                "id": record_id,
                "user_question": "question",
                "system_reply": "reply",
                "knowledge_base": "" if empty_knowledge_base else "knowledge",
            }
            for record_id in ids
        ]
    ).encode()


def _success(record: ReplyRecord) -> SuccessfulPrediction:
    return SuccessfulPrediction(
        kind="success",
        id=record.id,
        result=ClassificationResult(
            is_hallucination=False,
            labels=[],
            primary_type=None,
            severity=None,
            review_required=True,
            claims=[],
            omissions=[],
            summary="normal",
        ),
        engine="llm",
        model_name="model-1",
        detector_version="baseline-v1",
        config_hash=content_hash(_detector_config()),
        attempt_count=1,
    )


class ScriptedDetector:
    def __init__(self, fail_once_id: str | None = None) -> None:
        self._fail_once_id = fail_once_id
        self._calls: dict[str, int] = {}

    def detect_batch(
        self, records: list[ReplyRecord], detector: BaselineDetectorConfig
    ) -> BatchDetectionResult:
        results: list[PredictionResult] = []
        for record in records:
            self._calls[record.id] = self._calls.get(record.id, 0) + 1
            if record.id == self._fail_once_id and self._calls[record.id] == 1:
                results.append(
                    FailedPrediction(
                        kind="failure",
                        id=record.id,
                        error_code="timeout",
                        error_summary="timed out",
                        attempt_count=1,
                        model_name="model-1",
                    )
                )
            else:
                results.append(_success(record))
        return BatchDetectionResult(
            schema_version="1.0",
            results=results,
            input_hash=content_hash([record.model_dump(mode="json") for record in records]),
            detector_config_hash=content_hash(detector),
            network_attempt_count=len(results),
            provider_usage=ProviderUsage(
                prompt_tokens=len(results),
                completion_tokens=len(results),
                total_tokens=2 * len(results),
            ),
            stopped_reason=None,
        )


def _service(
    tmp_path: Path, engine: ScriptedDetector, environment: dict[str, str] | None = None
) -> RunService:
    registry = RunRegistry(uuid_factory=iter(["run-1", "run-2", "run-3"]).__next__)
    store = ArtifactStore(tmp_path / "runtime")
    detection = DetectionService(registry, engine, _detector_config(), artifact_store=store)
    return RunService(
        registry,
        detection,
        InProcessExecutor(),
        detector=_detector_config(),
        environment=_environment() if environment is None else environment,
    )


def test_all_success_auto_freezes_and_persists_snapshot(tmp_path: Path) -> None:
    service = _service(tmp_path, ScriptedDetector())

    summary = service.create(CreateRunRequest(), _reply_bytes(["h01", "h02"]))
    service.wait_for_test(summary.run_id)

    run = service.progress(summary.run_id)
    assert run.state is RunState.frozen
    assert run.success_count == 2 and run.failure_count == 0
    assert (tmp_path / "runtime" / run.id / "prediction_snapshot.json").exists()


def test_partial_retry_only_replaces_requested_failure_before_freeze(tmp_path: Path) -> None:
    service = _service(tmp_path, ScriptedDetector("h03"))
    run_id = service.create(CreateRunRequest(), _reply_bytes(["h01", "h03"])).run_id
    service.wait_for_test(run_id)
    assert service.progress(run_id).state is RunState.retryable_partial

    service.retry_failed(run_id, "h03", request_id="retry-1")
    service.wait_for_test(run_id)

    snapshot = service.snapshot(run_id)
    assert [item.id for item in snapshot.results] == ["h01", "h03"]
    assert snapshot.provider_usage.total_tokens == 6
    assert service.progress(run_id).state is RunState.frozen


def test_missing_provider_configuration_creates_no_run(tmp_path: Path) -> None:
    service = _service(tmp_path, ScriptedDetector(), environment={})

    with pytest.raises(ProviderConfigurationUnavailable):
        service.create(CreateRunRequest(), _reply_bytes(["h01"]))

    assert service.run_count_for_test() == 0


def test_empty_knowledge_warning_and_child_are_label_free(tmp_path: Path) -> None:
    service = _service(tmp_path, ScriptedDetector())
    run_id = service.create(
        CreateRunRequest(), _reply_bytes(["h01"], empty_knowledge_base=True)
    ).run_id
    service.wait_for_test(run_id)

    assert "empty knowledge_base" in service.progress(run_id).warnings
    child = service.create_child(run_id)
    assert child.parent_run_id == run_id
    assert child.success_count == 0 and child.failure_count == 0
