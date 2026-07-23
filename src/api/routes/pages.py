from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=Path(__file__).parents[1] / "templates")
router = APIRouter()


@router.get("/")
def index(request: Request):  # type: ignore[no-untyped-def]
    return templates.TemplateResponse(request, "pages/index.html")
