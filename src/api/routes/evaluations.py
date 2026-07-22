from __future__ import annotations

from fastapi import APIRouter, Request

from src.api.routes.runs import negotiated
from src.api.schemas.requests import IdempotentBody
from src.api.schemas.responses import MessageResponse
from src.api.security import enforce_state_change_boundary

router = APIRouter()


@router.post("/runs/{run_id}/evaluation")
def evaluate_run(request: Request, run_id: str, body: IdempotentBody):  # type: ignore[no-untyped-def]
    enforce_state_change_boundary(request)
    return negotiated(
        request,
        f'<section id="evaluation" data-run-id="{run_id}">尚未生成</section>',
        MessageResponse(
            status="ok", detail="evaluation accepted", data={"request_id": body.request_id}
        ),
    )
