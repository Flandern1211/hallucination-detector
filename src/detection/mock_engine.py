"""Deterministic label-free mock inference for offline demonstrations."""

from typing import Literal

from src.detection.aggregator import aggregate
from src.domain.enums import HallucinationType, Severity
from src.domain.hashing import content_hash
from src.domain.models import (
    BaselineDetectorConfig,
    BatchDetectionResult,
    Claim,
    ClaimJudgement,
    ErrorAnalysis,
    ErrorAnalysisInput,
    ExperimentalSuggestionBody,
    ProviderUsage,
    PredictionResult,
    ReplyRecord,
    SuccessfulPrediction,
    SuccessfulErrorAnalysis,
)
from src.input.loader import reply_input_hash
from src.providers.base import ProviderCallResult
from src.providers.budget import TaskBudget


class MockDetectionEngine:
    """Return a conservative all-positive baseline without reading labels."""

    def detect_batch(
        self, records: list[ReplyRecord], detector: BaselineDetectorConfig
    ) -> BatchDetectionResult:
        results: list[PredictionResult] = []
        for record in records:
            claim = Claim(
                claim_id=f"{record.id}-c01",
                text=record.system_reply,
                source_quote=record.system_reply,
                source_start_offset=0,
                source_end_offset=len(record.system_reply),
                kind="fact",
            )
            judgement = ClaimJudgement(
                claim=claim,
                verdict="unsupported",
                labels=[HallucinationType.unsupported_fabrication],
                severity=Severity.medium,
                evidence=None,
                core_relevance="medium",
                reason="mock 基线将确定性客服声明标记为需复核的无依据内容",
            )
            results.append(
                SuccessfulPrediction(
                    kind="success",
                    id=record.id,
                    result=aggregate([judgement], [], "mock 保守基线：检测到幻觉风险"),
                    engine="llm",
                    model_name="mock-v1",
                    detector_version=detector.version,
                    config_hash=content_hash(detector),
                    attempt_count=1,
                )
            )
        return BatchDetectionResult(
            schema_version="1.0",
            results=results,
            input_hash=reply_input_hash(records),
            detector_config_hash=content_hash(detector),
            network_attempt_count=len(results),
            provider_usage=ProviderUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            stopped_reason=None,
        )

    def analyze_errors(
        self,
        cases: list[ErrorAnalysisInput],
        detector: BaselineDetectorConfig,
        budget: TaskBudget,
    ) -> ProviderCallResult[list[ErrorAnalysis]]:
        del detector, budget
        analyses: list[ErrorAnalysis] = [
            SuccessfulErrorAnalysis(
                kind="success",
                case_ref=case.case_ref,
                error_kind=case.error_kind,
                primary_reason=(
                    "non_factual_expression_false_positive"
                    if case.error_kind == "false_positive"
                    else "claim_not_extracted"
                ),
                secondary_reasons=[],
                evidence=(
                    "mock 保守基线把所有回复判为阳性，正常表达因此形成误报"
                    if case.error_kind == "false_positive"
                    else "mock 输出未覆盖人工标注中的关键风险"
                ),
                proposed_improvement="真实检测应同时核验知识库证据并保留不确定结果供人工复核",
            )
            for case in cases
        ]
        return ProviderCallResult(
            value=analyses,
            model_name="mock-v1",
            usage=_zero_usage(),
            attempts=0,
            repaired=False,
        )

    def generate_suggestions(
        self,
        analyses: list[SuccessfulErrorAnalysis],
        detector: BaselineDetectorConfig,
        label_source: Literal["official_ground_truth", "human_revision"],
        budget: TaskBudget,
    ) -> ProviderCallResult[list[ExperimentalSuggestionBody]]:
        del analyses, detector, label_source, budget
        return ProviderCallResult(
            value=[
                ExperimentalSuggestionBody(
                    category="label_boundary",
                    target_stage="evidence_judgement",
                    rationale="保守全阳性基线会将与知识库一致的普通表达误判为幻觉",
                    proposed_change="仅在声明与知识库冲突或缺少必要依据时输出阳性标签",
                    known_risks=["边界收紧可能增加漏检，需要独立样本复核"],
                )
            ],
            model_name="mock-v1",
            usage=_zero_usage(),
            attempts=0,
            repaired=False,
        )


def _zero_usage() -> ProviderUsage:
    return ProviderUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)


__all__ = ["MockDetectionEngine"]
