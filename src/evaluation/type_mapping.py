"""Versioned compatibility mapping for manual and unified hallucination types."""

from importlib.resources import files
from typing import Literal

from pydantic import field_validator

from src.domain.enums import HallucinationType
from src.domain.models import FrozenMapping, FrozenSequence, StrictModel


class TypeCompatibility(StrictModel):
    schema_version: Literal["1.0"]
    version: str
    mapping: FrozenMapping[str, FrozenSequence[HallucinationType]]

    @field_validator("mapping")
    @classmethod
    def validate_mapping(
        cls, value: dict[str, list[HallucinationType]]
    ) -> dict[str, list[HallucinationType]]:
        if any(not key.strip() or not labels for key, labels in value.items()):
            raise ValueError("type compatibility entries must be non-empty")
        return value

    def compatible_types(self, manual_type: str) -> tuple[HallucinationType, ...] | None:
        values = self.mapping.get(manual_type)
        return None if values is None else tuple(values)


def load_type_compatibility() -> TypeCompatibility:
    raw = files("src.resources").joinpath("evaluation/type_compatibility.json").read_text("utf-8")
    return TypeCompatibility.model_validate_json(raw)


__all__ = ["TypeCompatibility", "load_type_compatibility"]
