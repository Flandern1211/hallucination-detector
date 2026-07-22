from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/runs/{run_id}/downloads/{artifact}")
def download(
    run_id: str,
    artifact: Literal[
        "predictions.json", "evaluation.json", "feedback.json", "suggestions.json", "report.md"
    ],
) -> JSONResponse:
    return JSONResponse({"run_id": run_id, "artifact": artifact, "status": "not_generated"})
