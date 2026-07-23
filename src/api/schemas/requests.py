from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from src.domain.models import ClassificationResult


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    request_id: str


class CreateRunBody(RequestModel):
    records: list[dict[str, object]]
    manual_review_enabled: bool = False
    external_processing_acknowledged: Literal[True]


class IdempotentBody(RequestModel):
    pass


class RetryFailedBody(RequestModel):
    record_id: str


class ReviewBody(RequestModel):
    status: Literal["confirmed_correct", "corrected"]
    source_prediction_hash: str
    reviewed_result: ClassificationResult

    @field_validator("reviewed_result", mode="before")
    @classmethod
    def parse_json_result(cls, value: object) -> object:
        if isinstance(value, dict):
            return ClassificationResult.model_validate_json(json.dumps(value, ensure_ascii=False))
        return value


class SuggestionBody(RequestModel):
    label_source: Literal["official_ground_truth", "human_revision"]
    external_processing_acknowledged: Literal[True]


class GroundTruthBody(RequestModel):
    records: list[dict[str, object]]
