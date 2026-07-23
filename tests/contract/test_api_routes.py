from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from pydantic import BaseModel

from src.api.app import create_app
from src.api.dependencies import ApplicationContainer
from src.api.dependencies import default_container
from src.domain.enums import RunState
from src.domain.models import BaselineDetectorConfig
from importlib.resources import files
from src.infrastructure.artifact_store import ArtifactStore


class _Payload(BaseModel):
    value: str


@dataclass
class _RunService:
    calls: list[tuple[str, tuple[Any, ...]]]

    def cancel(self, run_id: str) -> SimpleNamespace:
        self.calls.append(("cancel", (run_id,)))
        return SimpleNamespace(
            id=run_id,
            state=RunState.abandoned,
            total_count=2,
            completed_count=1,
            success_count=1,
            failure_count=0,
            warnings=(),
            persisted=True,
            persistence_error=None,
            parent_run_id=None,
        )

    def freeze(self, run_id: str) -> SimpleNamespace:
        self.calls.append(("freeze", (run_id,)))
        return SimpleNamespace(
            run_id=run_id, state=RunState.frozen, warnings=(), parent_run_id=None
        )

    def create_child(self, run_id: str) -> SimpleNamespace:
        self.calls.append(("child", (run_id,)))
        return SimpleNamespace(
            id="child-1",
            state=RunState.created,
            total_count=2,
            completed_count=0,
            success_count=0,
            failure_count=0,
            warnings=(),
            persisted=True,
            persistence_error=None,
            parent_run_id=run_id,
        )

    def retry_failed(self, run_id: str, record_id: str, *, request_id: str) -> SimpleNamespace:
        self.calls.append(("retry", (run_id, record_id, request_id)))
        return SimpleNamespace(
            run_id=run_id, state=RunState.running, warnings=(), parent_run_id=None
        )


@dataclass
class _ReviewService:
    calls: list[tuple[str, str, Any]]

    def save(self, run_id: str, record_id: str, request: Any) -> _Payload:
        self.calls.append((run_id, record_id, request))
        return _Payload(value="review-1")


@dataclass
class _SuggestionService:
    calls: list[tuple[str, Any]]

    def start(self, run_id: str, request: Any) -> SimpleNamespace:
        self.calls.append((run_id, request))
        return SimpleNamespace(run_id=run_id, status="completed")


def _client(container: ApplicationContainer) -> TestClient:
    return TestClient(create_app(container))


def _headers() -> dict[str, str]:
    return {"host": "localhost", "accept": "application/json"}


def test_run_mutation_routes_dispatch_to_application_service() -> None:
    run_service = _RunService([])
    client = _client(ApplicationContainer(run_service=run_service))

    cancel = client.post("/runs/run-1/cancel", json={"request_id": "c-1"}, headers=_headers())
    freeze = client.post("/runs/run-1/freeze", json={"request_id": "f-1"}, headers=_headers())
    child = client.post("/runs/run-1/children", json={"request_id": "ch-1"}, headers=_headers())
    retry = client.post(
        "/runs/run-1/retry-failed",
        json={"request_id": "r-1", "record_id": "h02"},
        headers=_headers(),
    )

    assert [response.status_code for response in (cancel, freeze, child, retry)] == [200] * 4
    assert run_service.calls == [
        ("cancel", ("run-1",)),
        ("freeze", ("run-1",)),
        ("child", ("run-1",)),
        ("retry", ("run-1", "h02", "r-1")),
    ]
    assert retry.json()["data"]["state"] == "running"


def test_review_route_validates_body_and_saves_revision() -> None:
    review_service = _ReviewService([])
    client = _client(ApplicationContainer(review_service=review_service))
    reviewed_result = {
        "is_hallucination": False,
        "labels": [],
        "primary_type": None,
        "severity": None,
        "review_required": True,
        "claims": [],
        "omissions": [],
        "summary": "人工确认",
    }

    response = client.post(
        "/runs/run-1/records/h01/review",
        json={
            "request_id": "review-1",
            "status": "confirmed_correct",
            "source_prediction_hash": "a" * 64,
            "reviewed_result": reviewed_result,
        },
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["data"]["value"] == "review-1"
    assert review_service.calls[0][2].save_request_id == "review-1"


def test_suggestion_route_starts_real_application_service() -> None:
    suggestion_service = _SuggestionService([])
    client = _client(ApplicationContainer(suggestion_service=suggestion_service))

    response = client.post(
        "/runs/run-1/suggestions",
        json={
            "request_id": "suggest-1",
            "label_source": "official_ground_truth",
            "external_processing_acknowledged": True,
        },
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "completed"
    assert suggestion_service.calls[0][1].label_source == "official_ground_truth"


def test_download_route_serves_only_existing_allowlisted_artifacts(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "runtime")
    store.write_json("run-1", "predictions.json", {"source": "model_prediction"})
    client = _client(ApplicationContainer(artifact_store=store))

    response = client.get("/runs/run-1/downloads/predictions.json", headers=_headers())
    missing = client.get("/runs/run-1/downloads/evaluation.json", headers=_headers())

    assert response.status_code == 200
    assert response.json()["source"] == "model_prediction"
    assert "attachment" in response.headers["content-disposition"]
    assert missing.status_code == 404


def test_default_container_wires_every_public_application_service(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HALLUCINATION_API_KEY", "test-secret")
    monkeypatch.setenv("HALLUCINATION_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("HALLUCINATION_MODEL", "test-model")

    container = default_container()

    assert container.run_service is not None
    assert container.review_service is not None
    assert container.evaluation_service is not None
    assert container.suggestion_service is not None
    assert container.reporting_service is not None
    assert container.artifact_store is not None
    expected = BaselineDetectorConfig.model_validate_json(
        files("src.resources").joinpath("detectors/baseline.json").read_text("utf-8")
    )
    assert container.detector_config == expected
