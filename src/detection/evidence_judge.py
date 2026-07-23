from src.domain.models import (
    BaselineDetectorConfig,
    Claim,
    ClaimJudgement,
    ReplyRecord,
    validate_evidence_quote,
)
from src.providers.base import DetectionInferenceProvider, ProviderCallResult, ProviderFailure
from src.providers.budget import TaskBudget


class EvidenceJudge:
    def __init__(self, provider: DetectionInferenceProvider) -> None:
        self._provider = provider

    def judge(
        self,
        record: ReplyRecord,
        claim: Claim,
        detector: BaselineDetectorConfig,
        budget: TaskBudget,
    ) -> ProviderCallResult[ClaimJudgement]:
        result = self._provider.judge_claim(record, claim, detector, budget)
        try:
            if result.value.claim != claim:
                raise ValueError("provider changed the claim")
            if result.value.evidence is not None:
                validate_evidence_quote(result.value.evidence, record.knowledge_base)
        except ValueError as exc:
            raise ProviderFailure(
                error_code="invalid_structure",
                error_summary=f"claim judgement failed local validation: {exc}",
                attempts=result.attempts,
                model_name=result.model_name,
                usage=result.usage,
            ) from exc
        return result
