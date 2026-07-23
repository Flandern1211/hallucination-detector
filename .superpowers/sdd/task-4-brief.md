### Task 4: Deterministic Aggregation and Three-Stage Detection

**Files:**
- Create: `src/detection/claim_extractor.py`
- Create: `src/detection/evidence_judge.py`
- Create: `src/detection/completeness_checker.py`
- Create: `src/detection/aggregator.py`
- Create: `src/detection/orchestrator.py`
- Create: `src/providers/base.py`
- Create: `src/providers/budget.py`
- Create: `tests/unit/test_aggregation.py`
- Create: `tests/unit/test_detection_orchestrator.py`
- Create: `tests/isolation/test_detection_label_isolation.py`

**Interfaces:**
- Consumes: `ReplyRecord` and `BaselineDetectorConfig` from Task 2.
- Produces: `ProviderCallResult[T](value: T, model_name: str, usage: ProviderUsage, attempts: int, repaired: bool)`; `DetectionInferenceProvider` and `SuggestionInferenceProvider` protocols; `TaskBudget(request_limit: int, token_limit: int, deadline_seconds: float, clock: Callable[[], float], cancel_event: threading.Event)` exposing `before_request()` and `record_usage(usage: ProviderUsage)`; `aggregate(judgements: list[ClaimJudgement], omissions: list[OmissionFinding], summary: str) -> ClassificationResult`; `DetectionEngine.detect_batch(records: list[ReplyRecord], detector: BaselineDetectorConfig, on_progress: Callable[[ProgressEvent], None] | None = None) -> BatchDetectionResult`.

- [ ] **Step 1: Write aggregation and isolation tests**

```python
def test_primary_type_uses_risk_evidence_relevance_then_stable_order() -> None:
    result = aggregate(
        judgements=[unsupported("能力越界", severity="中", relevance="high")],
        omissions=[omission("关键遗漏或歪曲", severity="高", relevance="low")],
        summary="发现风险",
    )
    assert result.labels == [HallucinationType.CAPABILITY, HallucinationType.OMISSION]
    assert result.primary_type is HallucinationType.OMISSION
    assert result.severity is Severity.HIGH


def test_zero_claims_and_omissions_is_normal_but_requires_review() -> None:
    result = aggregate([], [], "未提取到可核验声明")
    assert result.is_hallucination is False
    assert result.labels == []
    assert result.review_required is True


def test_detection_provider_payload_never_contains_label_sources() -> None:
    provider = CapturingDetectionProvider()
    DetectionOrchestrator(provider).detect_batch([reply_record()], baseline_config())
    serialized = json.dumps(provider.calls, ensure_ascii=False)
    assert "official_ground_truth" not in serialized
    assert "human_revision" not in serialized
    assert "risk_reference" not in serialized
```

- [ ] **Step 2: Confirm RED**

Run: `python -m pytest tests/unit/test_aggregation.py tests/unit/test_detection_orchestrator.py tests/isolation/test_detection_label_isolation.py -q`

Expected: FAIL on missing detector modules.

- [ ] **Step 3: Implement stable aggregation and stage wrappers**

```python
# src/providers/budget.py
from collections.abc import Callable
from threading import Event, Lock

from src.domain.models import ProviderUsage


class BudgetStop(RuntimeError):
    error_code: str


class TaskCancelled(BudgetStop):
    error_code = "cancelled"


class TaskDeadlineExceeded(BudgetStop):
    error_code = "run_deadline_exceeded"


class RequestBudgetExhausted(BudgetStop):
    error_code = "request_budget_exhausted"


class TokenBudgetExhausted(BudgetStop):
    error_code = "token_budget_exhausted"


class TaskBudget:
    def __init__(self, request_limit: int, token_limit: int, deadline_seconds: float,
                 clock: Callable[[], float], cancel_event: Event) -> None:
        self.request_limit = request_limit
        self.token_limit = token_limit
        self.deadline_seconds = deadline_seconds
        self.clock = clock
        self.cancel_event = cancel_event
        self.started_at = clock()
        self.network_attempt_count = 0
        self.usage = ProviderUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        self._lock = Lock()

    def before_request(self) -> None:
        with self._lock:
            if self.cancel_event.is_set():
                raise TaskCancelled
            if self.clock() >= self.started_at + self.deadline_seconds:
                raise TaskDeadlineExceeded
            if self.usage.total_tokens >= self.token_limit:
                raise TokenBudgetExhausted
            if self.network_attempt_count >= self.request_limit:
                raise RequestBudgetExhausted
            self.network_attempt_count += 1

    def record_usage(self, usage: ProviderUsage) -> None:
        with self._lock:
            self.usage = ProviderUsage(
                prompt_tokens=self.usage.prompt_tokens + usage.prompt_tokens,
                completion_tokens=self.usage.completion_tokens + usage.completion_tokens,
                total_tokens=self.usage.total_tokens + usage.total_tokens,
            )


# src/providers/base.py
from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar

from src.domain.models import (
    BaselineDetectorConfig, Claim, ClaimJudgement, ErrorAnalysis, ErrorAnalysisInput,
    ExperimentalSuggestionBody, OmissionFinding, ProviderUsage, ReplyRecord,
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


class DetectionInferenceProvider(Protocol):
    def extract_claims(self, record: ReplyRecord, detector: BaselineDetectorConfig,
                       budget: TaskBudget) -> ProviderCallResult[list[Claim]]:
        raise NotImplementedError

    def judge_claim(self, record: ReplyRecord, claim: Claim,
                    detector: BaselineDetectorConfig,
                    budget: TaskBudget) -> ProviderCallResult[ClaimJudgement]:
        raise NotImplementedError

    def find_omissions(self, record: ReplyRecord, detector: BaselineDetectorConfig,
                       budget: TaskBudget) -> ProviderCallResult[list[OmissionFinding]]:
        raise NotImplementedError


class SuggestionInferenceProvider(Protocol):
    def analyze_errors(self, cases: list[ErrorAnalysisInput], detector: BaselineDetectorConfig,
                       budget: TaskBudget) -> ProviderCallResult[list[ErrorAnalysis]]:
        raise NotImplementedError

    def generate_suggestions(
        self, analyses: list[SuccessfulErrorAnalysis], detector: BaselineDetectorConfig,
        label_source: Literal["official_ground_truth", "human_revision"], budget: TaskBudget,
    ) -> ProviderCallResult[list[ExperimentalSuggestionBody]]:
        raise NotImplementedError


# src/detection/aggregator.py
TYPE_ORDER = {label: index for index, label in enumerate(HallucinationType)}
SEVERITY_RANK = {Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1}
EVIDENCE_RANK = {"contradicted": 3, "omission": 2, "unsupported": 1}
RELEVANCE_RANK = {"high": 3, "medium": 2, "low": 1}


def aggregate(judgements: list[ClaimJudgement], omissions: list[OmissionFinding],
              summary: str) -> ClassificationResult:
    findings = finding_candidates(judgements, omissions)
    labels = stable_unique_labels(findings)
    if not findings:
        return ClassificationResult(is_hallucination=False, labels=[], primary_type=None,
            severity=None, review_required=not judgements or any_unverifiable(judgements),
            claims=judgements, omissions=omissions, summary=summary)
    winner = max(findings, key=finding_priority)
    return ClassificationResult(is_hallucination=True, labels=labels,
        primary_type=winner.label, severity=max((item.severity for item in findings),
        key=SEVERITY_RANK.__getitem__), review_required=any_unverifiable(judgements),
        claims=judgements, omissions=omissions, summary=summary)
```

The orchestrator processes records sequentially, assigns claim IDs after `(start, end, provider_index)` sorting, validates reply/evidence slices locally, makes at most 1 extraction + 10 judgements + 1 omission call, converts each record exception to exactly one `FailedPrediction`, and never reorders the input.

- [ ] **Step 4: Run focused tests and refactor only detector duplication**

Run: `python -m pytest tests/unit/test_aggregation.py tests/unit/test_detection_orchestrator.py tests/isolation/test_detection_label_isolation.py -q`

Expected: PASS for supported/contradicted/unsupported/unverifiable combinations, claim limit 10, partial failures, and label isolation.

- [ ] **Step 5: Request approval and commit**

```powershell
git add src/detection src/providers/base.py src/providers/budget.py tests/unit/test_aggregation.py tests/unit/test_detection_orchestrator.py tests/isolation/test_detection_label_isolation.py
git commit -m "feat: add evidence-first detection pipeline"
```

