from importlib.resources import files

from src.detection.orchestrator import DetectionOrchestrator
from src.domain.enums import HallucinationType, Severity
from src.domain.models import (
    BaselineDetectorConfig,
    Claim,
    ClaimJudgement,
    EvidenceReference,
    OmissionFinding,
    ProviderUsage,
    ReplyRecord,
)
from src.providers.base import ProviderCallResult, ProviderFailure
from src.providers.budget import TaskBudget


def _config() -> BaselineDetectorConfig:
    payload = files("src.resources").joinpath("detectors/baseline.json").read_text("utf-8")
    return BaselineDetectorConfig.model_validate_json(payload)


def _record(record_id: str = "h01") -> ReplyRecord:
    return ReplyRecord(
        id=record_id,
        user_question="退款多久到账？",
        system_reply="退款需要三个工作日，已经完成退款。",
        knowledge_base="退款需要三个工作日。客服不能直接完成退款。",
    )


_USAGE = ProviderUsage(prompt_tokens=4, completion_tokens=2, total_tokens=6)


class ScriptedProvider:
    def __init__(self) -> None:
        self.judged_claim_ids: list[str] = []

    def extract_claims(
        self, record: ReplyRecord, detector: BaselineDetectorConfig, budget: TaskBudget
    ) -> ProviderCallResult[list[Claim]]:
        del detector, budget
        reply = record.system_reply
        first = "退款需要三个工作日"
        second = "已经完成退款"
        return ProviderCallResult(
            value=[
                Claim(
                    claim_id="provider-2",
                    text=second,
                    source_quote=second,
                    source_start_offset=reply.index(second),
                    source_end_offset=reply.index(second) + len(second),
                    kind="capability",
                ),
                Claim(
                    claim_id="provider-1",
                    text=first,
                    source_quote=first,
                    source_start_offset=reply.index(first),
                    source_end_offset=reply.index(first) + len(first),
                    kind="policy",
                ),
            ],
            model_name="model-1",
            usage=_USAGE,
            attempts=1,
            repaired=False,
        )

    def judge_claim(
        self,
        record: ReplyRecord,
        claim: Claim,
        detector: BaselineDetectorConfig,
        budget: TaskBudget,
    ) -> ProviderCallResult[ClaimJudgement]:
        del detector, budget
        self.judged_claim_ids.append(claim.claim_id)
        if claim.kind == "policy":
            quote = "退款需要三个工作日"
            judgement = ClaimJudgement(
                claim=claim,
                verdict="supported",
                labels=[],
                severity=None,
                evidence=EvidenceReference(
                    quote=quote,
                    start_offset=record.knowledge_base.index(quote),
                    end_offset=record.knowledge_base.index(quote) + len(quote),
                ),
                core_relevance="high",
                reason="知识库支持",
            )
        else:
            judgement = ClaimJudgement(
                claim=claim,
                verdict="contradicted",
                labels=[HallucinationType.capability_overreach],
                severity=Severity.high,
                evidence=EvidenceReference(
                    quote="客服不能直接完成退款",
                    start_offset=record.knowledge_base.index("客服不能直接完成退款"),
                    end_offset=record.knowledge_base.index("客服不能直接完成退款")
                    + len("客服不能直接完成退款"),
                ),
                core_relevance="high",
                reason="能力明确不具备",
            )
        return ProviderCallResult(judgement, "model-1", _USAGE, 1, False)

    def find_omissions(
        self, record: ReplyRecord, detector: BaselineDetectorConfig, budget: TaskBudget
    ) -> ProviderCallResult[list[OmissionFinding]]:
        del record, detector, budget
        return ProviderCallResult([], "model-1", _USAGE, 1, False)


def test_orchestrator_sorts_claims_assigns_ids_and_reports_true_totals() -> None:
    provider = ScriptedProvider()
    progress: list[object] = []

    batch = DetectionOrchestrator(provider).detect_batch(
        [_record()], _config(), on_progress=progress.append
    )

    prediction = batch.results[0]
    assert prediction.kind == "success"
    assert provider.judged_claim_ids == ["h01-c01", "h01-c02"]
    assert [item.claim.claim_id for item in prediction.result.claims] == ["h01-c01", "h01-c02"]
    assert prediction.attempt_count == 4
    assert batch.network_attempt_count == 4
    assert batch.provider_usage.total_tokens == 24
    assert len(progress) == 1


class ClaimLimitProvider(ScriptedProvider):
    def extract_claims(
        self, record: ReplyRecord, detector: BaselineDetectorConfig, budget: TaskBudget
    ) -> ProviderCallResult[list[Claim]]:
        one = super().extract_claims(record, detector, budget).value[0]
        return ProviderCallResult([one] * 11, "model-1", _USAGE, 1, False)


def test_claim_limit_failure_stops_before_judgement_and_omission() -> None:
    provider = ClaimLimitProvider()

    batch = DetectionOrchestrator(provider).detect_batch([_record()], _config())

    failure = batch.results[0]
    assert failure.kind == "failure"
    assert failure.error_code == "claim_limit_exceeded"
    assert failure.attempt_count == 1
    assert provider.judged_claim_ids == []


class PartialFailureProvider(ScriptedProvider):
    def extract_claims(
        self, record: ReplyRecord, detector: BaselineDetectorConfig, budget: TaskBudget
    ) -> ProviderCallResult[list[Claim]]:
        if record.id == "h02":
            raise ProviderFailure(
                error_code="timeout",
                error_summary="provider request timed out",
                attempts=2,
                model_name=None,
            )
        return super().extract_claims(record, detector, budget)


def test_record_failure_is_isolated_and_input_order_is_preserved() -> None:
    records = [_record("h01"), _record("h02"), _record("h03")]

    batch = DetectionOrchestrator(PartialFailureProvider()).detect_batch(records, _config())

    assert [result.id for result in batch.results] == ["h01", "h02", "h03"]
    assert [result.kind for result in batch.results] == ["success", "failure", "success"]
    assert batch.results[1].attempt_count == 2
    assert batch.network_attempt_count == 10


def test_invalid_local_evidence_slice_becomes_one_failed_prediction() -> None:
    class InvalidEvidenceProvider(ScriptedProvider):
        def judge_claim(
            self,
            record: ReplyRecord,
            claim: Claim,
            detector: BaselineDetectorConfig,
            budget: TaskBudget,
        ) -> ProviderCallResult[ClaimJudgement]:
            result = super().judge_claim(record, claim, detector, budget)
            if result.value.evidence is None:
                return result
            invalid = result.value.model_copy(
                update={"evidence": result.value.evidence.model_copy(update={"start_offset": 1})}
            )
            return ProviderCallResult(invalid, "model-1", _USAGE, 1, False)

    batch = DetectionOrchestrator(InvalidEvidenceProvider()).detect_batch([_record()], _config())

    failure = batch.results[0]
    assert failure.kind == "failure"
    assert failure.error_code == "invalid_structure"
    assert failure.attempt_count >= 2
