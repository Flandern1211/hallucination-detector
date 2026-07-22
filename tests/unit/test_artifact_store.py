from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from src.infrastructure.artifact_store import (
    ArtifactCorrupt,
    ArtifactStore,
    UnsafeArtifactPath,
)


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int


def test_artifact_store_rejects_escape_and_corrupt_json(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "runtime")
    with pytest.raises(UnsafeArtifactPath):
        store.export_path("run-1", "../task4_replies.json")
    path = store.write_json("run-1", "prediction_snapshot.json", Snapshot(value=1))
    assert store.read_json("run-1", "prediction_snapshot.json", Snapshot).value == 1
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ArtifactCorrupt):
        store.read_json("run-1", "prediction_snapshot.json", Snapshot)


def test_export_path_rejects_absolute_path(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "runtime")
    with pytest.raises(UnsafeArtifactPath):
        store.export_path("run-1", str((tmp_path / "outside.json").resolve()))
