from __future__ import annotations

from importlib.resources import files
import json
from pathlib import Path

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.dependencies import ApplicationContainer, default_container
from src.application.detection_service import DetectionService
from src.application.evaluation_service import EvaluationService
from src.application.run_service import RunService
from src.domain.enums import HallucinationType, Severity
from src.domain.hashing import content_hash
from src.domain.models import (
    BaselineDetectorConfig,
    BatchDetectionResult,
    Claim,
    ClaimJudgement,
    ClassificationResult,
    EvidenceReference,
    ProviderUsage,
    PredictionResult,
    ReplyRecord,
    SuccessfulPrediction,
)
from src.evaluation.type_mapping import load_type_compatibility
from src.infrastructure.artifact_store import ArtifactStore
from src.infrastructure.in_process_executor import InProcessExecutor
from src.infrastructure.run_registry import RunRegistry


def _detector_config() -> BaselineDetectorConfig:
    return BaselineDetectorConfig.model_validate_json(
        files("src.resources").joinpath("detectors/baseline.json").read_text("utf-8")
    )


class _DeterministicDetector:
    def detect_batch(
        self, records: list[ReplyRecord], detector: BaselineDetectorConfig
    ) -> BatchDetectionResult:
        results: list[PredictionResult] = []
        for record in records:
            hallucination = record.id == "h02"
            claims = (
                [
                    ClaimJudgement(
                        claim=Claim(
                            claim_id="h02-c01",
                            text="蓝牙版本为5.3",
                            source_quote="蓝牙5.3",
                            source_start_offset=0,
                            source_end_offset=5,
                            kind="fact",
                        ),
                        verdict="contradicted",
                        labels=[HallucinationType.knowledge_conflict],
                        severity=Severity.high,
                        evidence=EvidenceReference(quote="蓝牙5.0", start_offset=0, end_offset=5),
                        core_relevance="high",
                        reason="与知识库参数冲突",
                    )
                ]
                if hallucination
                else []
            )
            classification = ClassificationResult(
                is_hallucination=hallucination,
                labels=[HallucinationType.knowledge_conflict] if hallucination else [],
                primary_type=HallucinationType.knowledge_conflict if hallucination else None,
                severity=Severity.high if hallucination else None,
                review_required=not hallucination,
                claims=claims,
                omissions=[],
                summary="检测到知识冲突" if hallucination else "未发现幻觉风险",
            )
            results.append(
                SuccessfulPrediction(
                    kind="success",
                    id=record.id,
                    result=classification,
                    engine="llm",
                    model_name="deterministic-test",
                    detector_version=detector.version,
                    config_hash=content_hash(detector),
                    attempt_count=1,
                )
            )
        return BatchDetectionResult(
            schema_version="1.0",
            results=results,
            input_hash=content_hash([record.model_dump(mode="json") for record in records]),
            detector_config_hash=content_hash(detector),
            network_attempt_count=2,
            provider_usage=ProviderUsage(prompt_tokens=2, completion_tokens=2, total_tokens=4),
            stopped_reason=None,
        )


def _container(tmp_path: Path) -> tuple[ApplicationContainer, RunService]:
    registry = RunRegistry(uuid_factory=lambda: "run-2-records")
    store = ArtifactStore(tmp_path / "runtime")
    detector = _detector_config()
    detection = DetectionService(registry, _DeterministicDetector(), detector, artifact_store=store)
    run_service = RunService(
        registry,
        detection,
        InProcessExecutor(),
        detector=detector,
        environment={
            "HALLUCINATION_API_KEY": "test-secret",
            "HALLUCINATION_BASE_URL": "https://provider.example/v1",
            "HALLUCINATION_MODEL": "deterministic-test",
        },
    )
    evaluation = EvaluationService(registry, load_type_compatibility(), artifact_store=store)
    return (
        ApplicationContainer(
            run_service=run_service,
            evaluation_service=evaluation,
            artifact_store=store,
        ),
        run_service,
    )


def test_two_record_detection_evaluation_and_download_workflow(tmp_path: Path) -> None:
    container, run_service = _container(tmp_path)
    client = TestClient(create_app(container))
    headers = {"host": "localhost", "accept": "application/json"}
    records = [
        {
            "id": "h01",
            "user_question": "退货政策？",
            "system_reply": "支持30天无理由退货。",
            "knowledge_base": "普通商品支持7天无理由退货。",
        },
        {
            "id": "h02",
            "user_question": "蓝牙版本？",
            "system_reply": "蓝牙5.3。",
            "knowledge_base": "蓝牙5.0。",
        },
    ]

    created = client.post(
        "/runs",
        json={
            "request_id": "create-1",
            "records": records,
            "manual_review_enabled": True,
            "external_processing_acknowledged": True,
        },
        headers=headers,
    )
    assert created.status_code == 200
    run_id = created.json()["data"]["run_id"]
    run_service.wait_for_test(run_id)

    results = client.get(f"/runs/{run_id}/results", headers=headers)
    assert results.status_code == 200
    assert [item["kind"] for item in results.json()["data"]["results"]] == [
        "success",
        "success",
    ]

    truth = [
        {
            "id": "h01",
            "is_hallucination": True,
            "hallucination_type": "政策编造",
            "detail": "退货政策与知识库冲突",
        },
        {
            "id": "h02",
            "is_hallucination": True,
            "hallucination_type": "参数编造",
            "detail": "蓝牙参数与知识库冲突",
        },
    ]
    loaded = client.post(
        f"/runs/{run_id}/ground-truth",
        json={"request_id": "truth-1", "records": truth},
        headers=headers,
    )
    evaluated = client.post(
        f"/runs/{run_id}/evaluation",
        json={"request_id": "eval-1"},
        headers=headers,
    )

    assert loaded.status_code == 200
    assert evaluated.status_code == 200
    metrics = evaluated.json()["data"]
    assert metrics["tp"] == 1
    assert metrics["fn"] == 1
    assert metrics["precision"]["value"] == 1.0
    assert metrics["recall"]["value"] == 0.5
    assert metrics["false_negative_ids"] == ["h01"]
    assert (
        client.get(f"/runs/{run_id}/downloads/predictions.json", headers=headers).status_code == 200
    )
    evaluation_download = client.get(f"/runs/{run_id}/downloads/evaluation.json", headers=headers)
    assert evaluation_download.status_code == 200
    assert evaluation_download.json()["source"] == "official_ground_truth"
    assert len(evaluation_download.json()["artifact_hash"]) == 64
    report = client.get(f"/runs/{run_id}/downloads/report.md", headers=headers)
    assert report.status_code == 200
    assert "## 分类定义" in report.text
    assert "## 漏检" in report.text
    assert "## AI 工具使用情况" in report.text


def test_full_twenty_record_mock_api_workflow(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    repository_root = Path(__file__).parents[2]
    records = json.loads((repository_root / "task4_replies.json").read_text("utf-8"))
    truth = json.loads((repository_root / "task4_ground_truth.json").read_text("utf-8"))
    monkeypatch.setenv("HALLUCINATION_API_KEY", "mock-key")
    monkeypatch.setenv("HALLUCINATION_BASE_URL", "https://mock.invalid/v1")
    monkeypatch.setenv("HALLUCINATION_MODEL", "mock")
    monkeypatch.chdir(tmp_path)
    container = default_container()
    client = TestClient(create_app(container))
    headers = {"host": "localhost", "accept": "application/json"}
    assert client.get("/", headers=headers).status_code == 200

    created = client.post(
        "/runs",
        json={
            "request_id": "create-20",
            "records": records,
            "manual_review_enabled": True,
            "external_processing_acknowledged": True,
        },
        headers=headers,
    )
    assert created.status_code == 200
    run_id = created.json()["data"]["run_id"]
    run_service = container.run_service
    assert isinstance(run_service, RunService)
    run_service.wait_for_test(run_id)

    result_response = client.get(f"/runs/{run_id}/results", headers=headers)
    assert result_response.status_code == 200
    result_items = result_response.json()["data"]["results"]
    assert len(result_items) == 20
    assert all(item["kind"] == "success" for item in result_items)
    assert all(item["attempt_count"] <= 3 for item in result_items)

    first = result_items[0]
    reviewed = client.post(
        f"/runs/{run_id}/records/{first['id']}/review",
        json={
            "request_id": "review-1",
            "status": "confirmed_correct",
            "source_prediction_hash": content_hash(first),
            "reviewed_result": first["result"],
        },
        headers=headers,
    )
    assert reviewed.status_code == 200

    loaded = client.post(
        f"/runs/{run_id}/ground-truth",
        json={"request_id": "truth-20", "records": truth},
        headers=headers,
    )
    evaluated = client.post(
        f"/runs/{run_id}/evaluation",
        json={"request_id": "evaluate-20"},
        headers=headers,
    )
    suggested = client.post(
        f"/runs/{run_id}/suggestions",
        json={
            "request_id": "suggest-20",
            "label_source": "official_ground_truth",
            "external_processing_acknowledged": True,
        },
        headers=headers,
    )

    assert loaded.status_code == 200
    assert suggested.status_code == 200
    assert evaluated.status_code == 200
    metrics = evaluated.json()["data"]
    assert (metrics["tp"], metrics["fp"], metrics["tn"], metrics["fn"]) == (18, 2, 0, 0)
    assert metrics["precision"]["value"] == 0.9
    assert metrics["recall"]["value"] == 1.0
    assert metrics["false_positive_ids"] == ["h12", "h16"]
    assert metrics["false_negative_ids"] == []

    expected_sources = {
        "predictions.json": "model_prediction",
        "evaluation.json": "official_ground_truth",
        "feedback.json": "human_revision",
        "suggestions.json": "experimental_suggestion",
    }
    for filename, source in expected_sources.items():
        download = client.get(f"/runs/{run_id}/downloads/{filename}", headers=headers)
        assert download.status_code == 200
        assert download.json()["source"] == source
        assert len(download.json()["artifact_hash"]) == 64
    assert client.get(f"/runs/{run_id}/downloads/report.md", headers=headers).status_code == 200
