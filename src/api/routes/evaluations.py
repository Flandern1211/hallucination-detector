from __future__ import annotations

import json
from fastapi import APIRouter, Request

from src.api.routes.runs import negotiated
from src.api.schemas.requests import GroundTruthBody, IdempotentBody
from src.api.schemas.responses import MessageResponse
from src.api.security import enforce_state_change_boundary

router = APIRouter()


@router.post("/runs/{run_id}/evaluation")
def evaluate_run(request: Request, run_id: str, body: IdempotentBody):  # type: ignore[no-untyped-def]
    enforce_state_change_boundary(request)
    service = request.app.state.container.evaluation_service
    if service is None:
        raise RuntimeError("evaluation service unavailable")
    try:
        result = service.evaluate(run_id, body.request_id)
    except RuntimeError as exc:
        return negotiated(
            request,
            f'<section id="evaluation">评测失败：{exc}</section>',
            MessageResponse(status="error", detail=str(exc)),
            400,
        )
    return negotiated(
        request,
        f'<section id="evaluation" data-run-id="{run_id}"><pre>{result.model_dump_json(indent=2)}</pre></section>',
        MessageResponse(
            status="ok", detail="evaluation complete", data=result.model_dump(mode="json")
        ),
    )


@router.post("/runs/{run_id}/ground-truth")
def load_ground_truth(request: Request, run_id: str, body: GroundTruthBody):  # type: ignore[no-untyped-def]
    enforce_state_change_boundary(request)
    service = request.app.state.container.evaluation_service
    if service is None:
        raise RuntimeError("evaluation service unavailable")
    try:
        summary = service.load_ground_truth(
            run_id, json.dumps(body.records).encode(), body.request_id
        )
    except RuntimeError as exc:
        return negotiated(
            request,
            f'<section id="evaluation">标注加载失败：{exc}</section>',
            MessageResponse(status="error", detail=str(exc)),
            400,
        )
    return negotiated(
        request,
        '<section id="evaluation">官方标注已加载，可开始评测。</section>',
        MessageResponse(
            status="ok", detail="ground truth loaded", data=summary.model_dump(mode="json")
        ),
    )
