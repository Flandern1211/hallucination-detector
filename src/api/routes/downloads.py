from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from src.reporting.exporter import ExportInputs, render_markdown_report

router = APIRouter()


@router.get("/runs/{run_id}/downloads/{artifact}")
def download(
    request: Request,
    run_id: str,
    artifact: Literal[
        "predictions.json", "evaluation.json", "feedback.json", "suggestions.json", "report.md"
    ],
) -> Response:
    store = request.app.state.container.artifact_store
    if store is None:
        raise HTTPException(503, "artifact store unavailable")
    if artifact == "report.md":
        predictions_path = store.export_path(run_id, "predictions.json")
        if not predictions_path.is_file():
            raise HTTPException(404, "predictions not generated")

        def optional_json(filename: str):  # type: ignore[no-untyped-def]
            candidate = store.export_path(run_id, filename)
            return json.loads(candidate.read_text("utf-8")) if candidate.is_file() else None

        detector = request.app.state.container.detector_config
        definitions = (
            {}
            if detector is None
            else {
                label.value: detail
                for label, detail in detector.hallucination_type_definitions.items()
            }
        )
        report = render_markdown_report(
            ExportInputs(
                predictions=json.loads(predictions_path.read_text("utf-8")),
                evaluation=optional_json("evaluation.json"),
                feedback=optional_json("feedback.json"),
                suggestions=optional_json("suggestions.json"),
                classification_definitions=definitions,
                ai_tool_usage=(
                    "Codex：开发、测试与接口验收",
                    "OpenAI 兼容 LLM 或 mock-v1：检测与误判分析",
                ),
            )
        )
        return Response(
            report,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="report.md"'},
        )
    path = store.export_path(run_id, artifact)
    if not path.is_file():
        raise HTTPException(404, "artifact not generated")
    return FileResponse(path, filename=artifact, media_type="application/json")
