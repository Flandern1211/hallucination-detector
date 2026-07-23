from __future__ import annotations

from fastapi import APIRouter, Request

from src.api.routes.runs import negotiated
from src.api.schemas.requests import SuggestionBody
from src.api.schemas.responses import MessageResponse
from src.api.security import enforce_state_change_boundary
from src.application.suggestion_service import SuggestionRequest

router = APIRouter()


@router.post("/runs/{run_id}/suggestions")
def suggestions(request: Request, run_id: str, body: SuggestionBody):  # type: ignore[no-untyped-def]
    enforce_state_change_boundary(request)
    service = request.app.state.container.suggestion_service
    if service is None:
        raise RuntimeError("suggestion service unavailable")
    summary = service.start(
        run_id,
        SuggestionRequest(
            label_source=body.label_source,
            external_processing_acknowledged=body.external_processing_acknowledged,
        ),
    )
    return negotiated(
        request,
        f'<section id="suggestions" data-run-id="{run_id}">小样本实验性建议，不代表效果提升</section>',
        MessageResponse(
            status="ok",
            detail="suggestions complete",
            data={"run_id": summary.run_id, "status": summary.status},
        ),
    )
