from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class MessageResponse(BaseModel):
    status: Literal["ok", "error"]
    detail: str
    data: dict[str, Any] = {}
