from __future__ import annotations

from fastapi import APIRouter, Request

from src.api.routes.runs import negotiated
from src.api.schemas.requests import SuggestionBody
from src.api.schemas.responses import MessageResponse
from src.api.security import enforce_state_change_boundary

router = APIRouter()


@router.post("/runs/{run_id}/suggestions")
def suggestions(request: Request, run_id: str, body: SuggestionBody):  # type: ignore[no-untyped-def]
    enforce_state_change_boundary(request)
    return negotiated(
        request,
        f'<section id="suggestions" data-run-id="{run_id}">小样本实验性建议，不代表效果提升</section>',
        MessageResponse(
            status="ok", detail="suggestions accepted", data={"label_source": body.label_source}
        ),
    )
