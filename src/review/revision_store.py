from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock

from src.domain.hashing import content_hash
from src.domain.models import ClassificationResult, HumanReviewRevision, SuccessfulPrediction
from src.review.diff import diff_results


def _utc_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class RevisionStore:
    _items: dict[tuple[str, str], list[HumanReviewRevision]] = field(default_factory=dict)
    _requests: dict[tuple[str, str], HumanReviewRevision] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def append(
        self,
        *,
        run_id: str,
        record_id: str,
        prediction: SuccessfulPrediction,
        status: str,
        save_request_id: str,
        reviewed_result: ClassificationResult,
        review_id_factory: Callable[[], str],
        clock: Callable[[], datetime],
    ) -> HumanReviewRevision:
        with self._lock:
            request_key = (run_id, save_request_id)
            existing = self._requests.get(request_key)
            if existing is not None:
                return existing

            key = (run_id, record_id)
            history = self._items.setdefault(key, [])
            previous = history[-1] if history else None
            created_at = clock()
            body = {
                "schema_version": "1.0",
                "review_id": review_id_factory(),
                "run_id": run_id,
                "record_id": record_id,
                "status": status,
                "source_prediction_hash": content_hash(prediction),
                "reviewed_result": reviewed_result.model_dump(mode="json"),
                "changed_fields": diff_results(prediction.result, reviewed_result),
                "revision_number": len(history) + 1,
                "save_request_id": save_request_id,
                "created_at_utc": created_at,
                "previous_event_hash": None if previous is None else previous.event_hash,
            }
            hash_body = {**body, "created_at_utc": _utc_z(created_at)}
            revision = HumanReviewRevision.model_validate(
                {**body, "event_hash": content_hash(hash_body)}
            )
            history.append(revision)
            self._requests[request_key] = revision
            return revision

    def latest_for_run(self, run_id: str) -> list[HumanReviewRevision]:
        with self._lock:
            latest = [
                history[-1]
                for (item_run_id, _), history in self._items.items()
                if item_run_id == run_id and history
            ]
        return sorted(latest, key=lambda item: item.record_id)
