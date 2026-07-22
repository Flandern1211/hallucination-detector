from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    request_id: str


class CreateRunBody(RequestModel):
    records: list[dict[str, object]]
    manual_review_enabled: bool = False
    external_processing_acknowledged: Literal[True]


class IdempotentBody(RequestModel):
    pass


class SuggestionBody(RequestModel):
    label_source: Literal["official_ground_truth", "human_revision"]
    external_processing_acknowledged: Literal[True]
