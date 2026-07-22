from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="src/api/templates")
router = APIRouter()


@router.get("/")
def index(request: Request):  # type: ignore[no-untyped-def]
    return templates.TemplateResponse("pages/index.html", {"request": request})
