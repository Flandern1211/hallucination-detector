from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from src.api.schemas.requests import CreateRunBody, IdempotentBody
from src.api.schemas.responses import MessageResponse
from src.api.security import enforce_state_change_boundary

router = APIRouter()


def negotiated(request: Request, html: str, payload: MessageResponse, status_code: int = 200):  # type: ignore[no-untyped-def]
    if request.headers.get("HX-Request", "").lower() == "true":
        return HTMLResponse(html, status_code=status_code)
    accept = request.headers.get("accept", "")
    if "application/json" in accept or "*/*" in accept:
        return JSONResponse(payload.model_dump(mode="json"), status_code=status_code)
    return JSONResponse({"detail": "not acceptable"}, status_code=406)


@router.post("/runs")
def create_run(request: Request, body: CreateRunBody):  # type: ignore[no-untyped-def]
    enforce_state_change_boundary(request)
    return negotiated(
        request,
        '<section id="run-summary">运行已创建</section>',
        MessageResponse(
            status="ok", detail="run created", data={"record_count": len(body.records)}
        ),
    )


@router.get("/runs/{run_id}/progress")
def progress(request: Request, run_id: str):  # type: ignore[no-untyped-def]
    return negotiated(
        request,
        f'<section id="progress" aria-live="polite">run {run_id}</section>',
        MessageResponse(status="ok", detail="progress", data={"run_id": run_id}),
    )


@router.get("/runs/{run_id}/results")
def results(request: Request, run_id: str):  # type: ignore[no-untyped-def]
    return HTMLResponse(f'<section id="results" data-run-id="{run_id}">尚未生成</section>')


@router.post("/runs/{run_id}/cancel")
@router.post("/runs/{run_id}/freeze")
@router.post("/runs/{run_id}/retry-failed")
@router.post("/runs/{run_id}/children")
def mutate_run(request: Request, run_id: str, body: IdempotentBody):  # type: ignore[no-untyped-def]
    enforce_state_change_boundary(request)
    return negotiated(
        request,
        f'<section id="run-summary" data-run-id="{run_id}">ok</section>',
        MessageResponse(status="ok", detail="accepted", data={"request_id": body.request_id}),
    )
