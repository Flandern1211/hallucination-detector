from __future__ import annotations

from fastapi import APIRouter, Request

from src.api.routes.runs import negotiated
from src.api.schemas.requests import ReviewBody
from src.api.schemas.responses import MessageResponse
from src.api.security import enforce_state_change_boundary
from src.application.review_service import ReviewSaveRequest

router = APIRouter()


@router.post("/runs/{run_id}/records/{record_id}/review")
def save_review(request: Request, run_id: str, record_id: str, body: ReviewBody):  # type: ignore[no-untyped-def]
    enforce_state_change_boundary(request)
    service = request.app.state.container.review_service
    if service is None:
        raise RuntimeError("review service unavailable")
    revision = service.save(
        run_id,
        record_id,
        ReviewSaveRequest(
            status=body.status,
            save_request_id=body.request_id,
            source_prediction_hash=body.source_prediction_hash,
            reviewed_result=body.reviewed_result,
        ),
    )
    return negotiated(
        request,
        f'<section id="review" data-run-id="{run_id}" data-record-id="{record_id}">ok</section>',
        MessageResponse(status="ok", detail="review saved", data=revision.model_dump(mode="json")),
    )
