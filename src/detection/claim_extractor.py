from src.domain.models import BaselineDetectorConfig, Claim, ReplyRecord, validate_claim_quote
from src.providers.base import DetectionInferenceProvider, ProviderCallResult, ProviderFailure
from src.providers.budget import TaskBudget


class ClaimExtractor:
    def __init__(self, provider: DetectionInferenceProvider) -> None:
        self._provider = provider

    def extract(
        self, record: ReplyRecord, detector: BaselineDetectorConfig, budget: TaskBudget
    ) -> ProviderCallResult[list[Claim]]:
        result = self._provider.extract_claims(record, detector, budget)
        if len(result.value) > detector.max_claims:
            raise ProviderFailure(
                error_code="claim_limit_exceeded",
                error_summary="claim extraction exceeded the configured limit",
                attempts=result.attempts,
                model_name=result.model_name,
                usage=result.usage,
            )
        indexed = list(enumerate(result.value))
        indexed.sort(
            key=lambda item: (
                item[1].source_start_offset,
                item[1].source_end_offset,
                item[0],
            )
        )
        claims: list[Claim] = []
        try:
            for position, (_, claim) in enumerate(indexed, start=1):
                assigned = Claim.model_validate(
                    {**claim.model_dump(), "claim_id": f"{record.id}-c{position:02d}"}
                )
                validate_claim_quote(assigned, record.system_reply)
                claims.append(assigned)
        except ValueError as exc:
            raise ProviderFailure(
                error_code="invalid_structure",
                error_summary="claim output failed local validation",
                attempts=result.attempts,
                model_name=result.model_name,
                usage=result.usage,
            ) from exc
        return ProviderCallResult(
            claims, result.model_name, result.usage, result.attempts, result.repaired
        )
