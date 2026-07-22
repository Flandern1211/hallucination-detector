from collections.abc import Callable
from threading import Event
from time import monotonic
from typing import Any, Protocol, cast

from src.detection.aggregator import aggregate
from src.detection.claim_extractor import ClaimExtractor
from src.detection.completeness_checker import CompletenessChecker
from src.detection.evidence_judge import EvidenceJudge
from src.domain.hashing import content_hash
from src.domain.models import (
    BaselineDetectorConfig,
    BatchDetectionResult,
    FailedPrediction,
    PredictionErrorCode,
    ProgressEvent,
    ProviderUsage,
    ReplyRecord,
    SuccessfulPrediction,
)
from src.providers.base import DetectionInferenceProvider, ProviderCallResult, ProviderFailure
from src.providers.budget import BudgetStop, TaskBudget


class DetectionEngine(Protocol):
    def detect_batch(
        self,
        records: list[ReplyRecord],
        detector: BaselineDetectorConfig,
        on_progress: Callable[[ProgressEvent], None] | None = None,
    ) -> BatchDetectionResult: ...


def _add_usage(left: ProviderUsage, right: ProviderUsage) -> ProviderUsage:
    return ProviderUsage(
        prompt_tokens=left.prompt_tokens + right.prompt_tokens,
        completion_tokens=left.completion_tokens + right.completion_tokens,
        total_tokens=left.total_tokens + right.total_tokens,
    )


class DetectionOrchestrator:
    def __init__(
        self,
        provider: DetectionInferenceProvider,
        *,
        budget: TaskBudget | None = None,
    ) -> None:
        self._extractor = ClaimExtractor(provider)
        self._judge = EvidenceJudge(provider)
        self._checker = CompletenessChecker(provider)
        self._budget = budget

    def detect_batch(
        self,
        records: list[ReplyRecord],
        detector: BaselineDetectorConfig,
        on_progress: Callable[[ProgressEvent], None] | None = None,
    ) -> BatchDetectionResult:
        budget = self._budget or TaskBudget(200, 250_000, 1800, monotonic, Event())
        results: list[SuccessfulPrediction | FailedPrediction] = []
        total_usage = ProviderUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        terminal_stop: BudgetStop | None = None

        for completed, record in enumerate(records, start=1):
            if terminal_stop is None:
                result, usage, stop = self._detect_record(record, detector, budget)
                total_usage = _add_usage(total_usage, usage)
                terminal_stop = stop
            else:
                error_code = cast(PredictionErrorCode, terminal_stop.error_code)
                result = FailedPrediction(
                    kind="failure",
                    id=record.id,
                    error_code=error_code,
                    error_summary="detection task stopped before the next request",
                    attempt_count=0,
                    model_name=None,
                )
            results.append(result)
            if on_progress is not None:
                on_progress(
                    ProgressEvent(
                        record_id=record.id,
                        completed_count=completed,
                        total_count=len(records),
                        outcome=result.kind,
                    )
                )

        stopped_reason = terminal_stop.error_code if terminal_stop is not None else None
        return BatchDetectionResult(
            schema_version="1.0",
            results=results,
            input_hash=content_hash([record.model_dump(mode="json") for record in records]),
            detector_config_hash=content_hash(detector),
            network_attempt_count=sum(item.attempt_count for item in results),
            provider_usage=total_usage,
            stopped_reason=stopped_reason,
        )

    def _detect_record(
        self, record: ReplyRecord, detector: BaselineDetectorConfig, budget: TaskBudget
    ) -> tuple[SuccessfulPrediction | FailedPrediction, ProviderUsage, BudgetStop | None]:
        attempts = 0
        usage = ProviderUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        model_name: str | None = None

        def accept(result: ProviderCallResult[Any]) -> None:
            nonlocal attempts, usage, model_name
            attempts += result.attempts
            usage = _add_usage(usage, result.usage)
            if model_name is None:
                model_name = result.model_name
            elif model_name != result.model_name:
                raise ProviderFailure(
                    error_code="provider_error",
                    error_summary="provider model changed during the detection task",
                    attempts=0,
                    model_name=result.model_name,
                )

        try:
            extraction = self._extractor.extract(record, detector, budget)
            accept(extraction)
            judgements = []
            for claim in extraction.value:
                judgement = self._judge.judge(record, claim, detector, budget)
                accept(judgement)
                judgements.append(judgement.value)
            omissions = self._checker.find(record, detector, budget)
            accept(omissions)
            summary = (
                "检测到幻觉风险"
                if any(item.labels for item in judgements) or omissions.value
                else "未发现幻觉风险"
            )
            classification = aggregate(judgements, omissions.value, summary)
            return (
                SuccessfulPrediction(
                    kind="success",
                    id=record.id,
                    result=classification,
                    engine="llm",
                    model_name=model_name or "unknown",
                    detector_version=detector.version,
                    config_hash=content_hash(detector),
                    attempt_count=attempts,
                ),
                usage,
                None,
            )
        except ProviderFailure as exc:
            attempts += exc.attempts
            usage = _add_usage(usage, exc.usage)
            return (
                FailedPrediction(
                    kind="failure",
                    id=record.id,
                    error_code=exc.error_code,
                    error_summary=exc.error_summary,
                    attempt_count=attempts,
                    model_name=exc.model_name or model_name,
                ),
                usage,
                None,
            )
        except BudgetStop as exc:
            return (
                FailedPrediction(
                    kind="failure",
                    id=record.id,
                    error_code=cast(PredictionErrorCode, exc.error_code),
                    error_summary="detection task budget stopped the request",
                    attempt_count=attempts,
                    model_name=model_name,
                ),
                usage,
                exc,
            )
        except Exception:
            return (
                FailedPrediction(
                    kind="failure",
                    id=record.id,
                    error_code="provider_error",
                    error_summary="unexpected provider failure",
                    attempt_count=max(attempts, 1),
                    model_name=model_name,
                ),
                usage,
                None,
            )
