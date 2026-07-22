from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar

from src.domain.models import (
    BaselineDetectorConfig,
    Claim,
    ClaimJudgement,
    ErrorAnalysis,
    ErrorAnalysisInput,
    ExperimentalSuggestionBody,
    OmissionFinding,
    PredictionErrorCode,
    ProviderUsage,
    ReplyRecord,
    SuccessfulErrorAnalysis,
)
from src.providers.budget import TaskBudget


T = TypeVar("T")


@dataclass(frozen=True)
class ProviderCallResult(Generic[T]):
    value: T
    model_name: str
    usage: ProviderUsage
    attempts: int
    repaired: bool


class ProviderFailure(RuntimeError):
    def __init__(
        self,
        *,
        error_code: PredictionErrorCode,
        error_summary: str,
        attempts: int,
        model_name: str | None,
        usage: ProviderUsage | None = None,
    ) -> None:
        super().__init__(error_summary)
        self.error_code = error_code
        self.error_summary = error_summary
        self.attempts = attempts
        self.model_name = model_name
        self.usage = usage or ProviderUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)


class DetectionInferenceProvider(Protocol):
    def extract_claims(
        self, record: ReplyRecord, detector: BaselineDetectorConfig, budget: TaskBudget
    ) -> ProviderCallResult[list[Claim]]: ...

    def judge_claim(
        self,
        record: ReplyRecord,
        claim: Claim,
        detector: BaselineDetectorConfig,
        budget: TaskBudget,
    ) -> ProviderCallResult[ClaimJudgement]: ...

    def find_omissions(
        self, record: ReplyRecord, detector: BaselineDetectorConfig, budget: TaskBudget
    ) -> ProviderCallResult[list[OmissionFinding]]: ...


class SuggestionInferenceProvider(Protocol):
    def analyze_errors(
        self,
        cases: list[ErrorAnalysisInput],
        detector: BaselineDetectorConfig,
        budget: TaskBudget,
    ) -> ProviderCallResult[list[ErrorAnalysis]]: ...

    def generate_suggestions(
        self,
        analyses: list[SuccessfulErrorAnalysis],
        detector: BaselineDetectorConfig,
        label_source: Literal["official_ground_truth", "human_revision"],
        budget: TaskBudget,
    ) -> ProviderCallResult[list[ExperimentalSuggestionBody]]: ...
