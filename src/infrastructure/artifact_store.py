from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from src.domain.hashing import canonical_bytes


class UnsafeArtifactPath(ValueError):
    pass


class ArtifactCorrupt(ValueError):
    pass


ModelT = TypeVar("ModelT", bound=BaseModel)


class ArtifactStore:
    def __init__(self, runtime_root: Path) -> None:
        self._runtime_root = runtime_root.resolve()
        self._runtime_root.mkdir(parents=True, exist_ok=True)

    def export_path(self, run_id: str, filename: str) -> Path:
        artifact_name = Path(filename)
        if artifact_name.is_absolute() or ".." in artifact_name.parts:
            raise UnsafeArtifactPath(f"unsafe artifact path: {filename!r}")
        candidate = (self._runtime_root / run_id / filename).resolve()
        if not candidate.is_relative_to(self._runtime_root):
            raise UnsafeArtifactPath(f"artifact path escapes runtime root: {filename!r}")
        return candidate

    def write_json(self, run_id: str, filename: str, value: object) -> Path:
        path = self.export_path(run_id, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = canonical_bytes(value)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
            json.loads(data)
            os.replace(temporary_path, path)
            return path
        except (OSError, TypeError, ValueError) as error:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            if isinstance(error, (TypeError, ValueError)):
                raise ArtifactCorrupt("artifact could not be serialized as JSON") from error
            raise

    def read_json(self, run_id: str, filename: str, model_type: type[ModelT]) -> ModelT:
        path = self.export_path(run_id, filename)
        try:
            return model_type.model_validate_json(path.read_bytes())
        except (OSError, ValidationError, ValueError) as error:
            raise ArtifactCorrupt(f"artifact is missing or corrupt: {path.name}") from error
