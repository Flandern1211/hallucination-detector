from __future__ import annotations

import json
from fastapi import APIRouter, Request, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse

from src.api.schemas.requests import CreateRunBody, IdempotentBody, RetryFailedBody
from src.api.schemas.responses import MessageResponse
from src.api.security import enforce_state_change_boundary
from src.application.models import CreateRunRequest
from src.domain.models import DetectionRunConfig

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
    service = request.app.state.container.run_service
    if service is None:
        raise HTTPException(503, "run service unavailable")
    config = DetectionRunConfig(
        detector_version="baseline-v1",
        manual_review_enabled=body.manual_review_enabled,
        external_processing_acknowledged=body.external_processing_acknowledged,
    )
    try:
        summary = service.create(CreateRunRequest(config=config), json.dumps(body.records).encode())
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return negotiated(
        request,
        '<section id="run-summary">运行已创建</section>',
        MessageResponse(
            status="ok",
            detail="run created",
            data={
                "run_id": summary.run_id,
                "state": summary.state.value,
                "record_count": len(body.records),
            },
        ),
    )


@router.get("/runs/{run_id}/progress")
def progress(request: Request, run_id: str):  # type: ignore[no-untyped-def]
    service = request.app.state.container.run_service
    try:
        value = service.progress(run_id)
    except Exception as exc:
        raise HTTPException(404, "run not found") from exc
    return negotiated(
        request,
        f'<section id="progress" aria-live="polite">{value.completed_count}/{value.total_count} ({value.state.value})</section>',
        MessageResponse(
            status="ok",
            detail="progress",
            data=value.__dict__
            if hasattr(value, "__dict__")
            else {
                "run_id": run_id,
                "state": value.state.value,
                "completed_count": value.completed_count,
                "total_count": value.total_count,
            },
        ),
    )


@router.get("/runs/{run_id}/results")
def results(request: Request, run_id: str):  # type: ignore[no-untyped-def]
    service = request.app.state.container.run_service
    try:
        snapshot = service.snapshot(run_id)
    except Exception as exc:
        raise HTTPException(404, "results unavailable") from exc
    payload = MessageResponse(status="ok", detail="results", data=snapshot.model_dump(mode="json"))
    return negotiated(
        request,
        f'<section id="results" data-run-id="{run_id}"><pre>{json.dumps(payload.data, ensure_ascii=False)}</pre></section>',
        payload,
    )


@router.post("/runs/{run_id}/cancel")
def cancel_run(request: Request, run_id: str, body: IdempotentBody):  # type: ignore[no-untyped-def]
    enforce_state_change_boundary(request)
    progress = request.app.state.container.run_service.cancel(run_id)
    return negotiated(
        request,
        '<section id="run-summary">cancelled</section>',
        MessageResponse(status="ok", detail="run cancelled", data=jsonable_encoder(progress)),
    )


@router.post("/runs/{run_id}/freeze")
def freeze_run(request: Request, run_id: str, body: IdempotentBody):  # type: ignore[no-untyped-def]
    enforce_state_change_boundary(request)
    summary = request.app.state.container.run_service.freeze(run_id)
    return negotiated(
        request,
        '<section id="run-summary">frozen</section>',
        MessageResponse(status="ok", detail="run frozen", data=jsonable_encoder(summary)),
    )


@router.post("/runs/{run_id}/children")
def child_run(request: Request, run_id: str, body: IdempotentBody):  # type: ignore[no-untyped-def]
    enforce_state_change_boundary(request)
    progress = request.app.state.container.run_service.create_child(run_id)
    return negotiated(
        request,
        '<section id="run-summary">child created</section>',
        MessageResponse(status="ok", detail="child run created", data=jsonable_encoder(progress)),
    )


@router.post("/runs/{run_id}/retry-failed")
def retry_failed(request: Request, run_id: str, body: RetryFailedBody):  # type: ignore[no-untyped-def]
    enforce_state_change_boundary(request)
    summary = request.app.state.container.run_service.retry_failed(
        run_id, body.record_id, request_id=body.request_id
    )
    return negotiated(
        request,
        '<section id="run-summary">retry started</section>',
        MessageResponse(status="ok", detail="retry started", data=jsonable_encoder(summary)),
    )
