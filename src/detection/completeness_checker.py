from src.domain.models import (
    BaselineDetectorConfig,
    OmissionFinding,
    ReplyRecord,
    validate_evidence_quote,
)
from src.providers.base import DetectionInferenceProvider, ProviderCallResult, ProviderFailure
from src.providers.budget import TaskBudget


class CompletenessChecker:
    def __init__(self, provider: DetectionInferenceProvider) -> None:
        self._provider = provider

    def find(
        self, record: ReplyRecord, detector: BaselineDetectorConfig, budget: TaskBudget
    ) -> ProviderCallResult[list[OmissionFinding]]:
        result = self._provider.find_omissions(record, detector, budget)
        try:
            for omission in result.value:
                validate_evidence_quote(omission.evidence, record.knowledge_base)
        except ValueError as exc:
            raise ProviderFailure(
                error_code="invalid_structure",
                error_summary="omission output failed local validation",
                attempts=result.attempts,
                model_name=result.model_name,
                usage=result.usage,
            ) from exc
        return result
