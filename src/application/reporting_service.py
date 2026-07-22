from __future__ import annotations

from typing import Any, Literal

from src.domain.hashing import content_hash
from src.reporting.exporter import ExportBundle, ExportInputs, build_all_exports


class InvalidExportArtifact(ValueError):
    pass


ArtifactSource = Literal[
    "model_prediction",
    "official_ground_truth",
    "human_revision",
    "experimental_suggestion",
    "markdown_report",
]

ARTIFACT_ALLOWLIST: dict[str, ArtifactSource] = {
    "predictions.json": "model_prediction",
    "evaluation.json": "official_ground_truth",
    "feedback.json": "human_revision",
    "suggestions.json": "experimental_suggestion",
    "report.md": "markdown_report",
}


class ReportingService:
    def build_exports(self, inputs: ExportInputs) -> ExportBundle:
        return build_all_exports(inputs)

    def source_for(self, artifact: str) -> ArtifactSource:
        return ARTIFACT_ALLOWLIST[artifact]

    def validate_export(self, artifact: dict[str, Any]) -> None:
        source = artifact.get("source")
        if source not in set(ARTIFACT_ALLOWLIST.values()) - {"markdown_report"}:
            raise InvalidExportArtifact("export source is not allowed")
        artifact_hash = artifact.get("artifact_hash")
        if artifact_hash != content_hash(artifact, frozenset({"artifact_hash"})):
            raise InvalidExportArtifact("export artifact hash does not match its content")
