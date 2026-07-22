from dataclasses import replace

import pytest

from src.domain.hashing import content_hash
from src.reporting.exporter import (
    ExportInputs,
    build_all_exports,
    export_evaluation,
    export_feedback,
    export_predictions,
    export_suggestions,
    markdown_fence,
    render_markdown_report,
)
from src.application.reporting_service import InvalidExportArtifact, ReportingService


def _complete_run(user_text: str = "普通用户文本") -> ExportInputs:
    predictions = {
        "schema_version": "1.0",
        "run_id": "run-1",
        "results": [
            {
                "kind": "success",
                "id": "h01",
                "result": {"is_hallucination": False},
                "model_name": "model-a",
                "config_hash": "a" * 64,
                "attempt_count": 1,
                "user_text": user_text,
            },
            {
                "kind": "failure",
                "id": "h02",
                "error_code": "timeout",
                "error_summary": "provider timeout",
                "attempt_count": 2,
            },
        ],
    }
    evaluation = {
        "schema_version": "1.0",
        "coverage": {"value": 0.5, "numerator": 1, "denominator": 2},
        "precision": {"value": 1.0, "numerator": 1, "denominator": 1},
        "false_negative_ids": ["h03"],
        "false_positive_ids": ["h11"],
    }
    feedback = {"reviewed_success_count": 1, "total_success_count": 1, "revisions": []}
    suggestions = {
        "warning": "小样本实验性建议，不代表效果提升",
        "analyses": [{"case_ref": "case-001", "primary_reason": "evidence_misread"}],
        "suggestions": [
            {
                "suggestion_id": "suggestion-001",
                "category": "prompt_principle",
                "target_stage": "evidence_judgement",
                "rationale": "通用理由",
                "proposed_change": "通用原则",
                "known_risks": ["误报风险"],
            }
        ],
    }
    return ExportInputs(
        predictions=predictions,
        evaluation=evaluation,
        feedback=feedback,
        suggestions=suggestions,
        classification_definitions={"知识冲突": "回复与知识库明确矛盾"},
        ai_tool_usage=("LLM 用于三阶段检测和实验性误差归纳；输出经过本地校验。",),
    )


def test_exports_mark_sources_contract_version_and_self_excluding_hash() -> None:
    exports = build_all_exports(_complete_run())

    assert exports.predictions["schema_version"] == "1.0"
    assert exports.predictions["source"] == "model_prediction"
    assert exports.evaluation is not None
    assert exports.evaluation["source"] == "official_ground_truth"
    assert exports.feedback is not None
    assert exports.feedback["source"] == "human_revision"
    assert exports.suggestions is not None
    assert exports.suggestions["source"] == "experimental_suggestion"
    assert exports.predictions["artifact_hash"] == content_hash(
        exports.predictions, frozenset({"artifact_hash"})
    )
    assert export_predictions({})["source"] == "model_prediction"
    assert export_evaluation({})["source"] == "official_ground_truth"
    assert export_feedback({})["source"] == "human_revision"
    assert export_suggestions({})["source"] == "experimental_suggestion"


def test_markdown_uses_longer_fence_and_never_emits_raw_html() -> None:
    report = render_markdown_report(_complete_run("</script> ``` <img src=x onerror=1>"))

    assert "<img" not in report and "</script>" not in report
    assert "````text" in report


@pytest.mark.parametrize(
    "term", ["validated", "improved", "upgrade", "out-of-fold", "full-data replay"]
)
def test_report_never_describes_suggestions_with_forbidden_terms(term: str) -> None:
    assert term not in render_markdown_report(_complete_run()).lower()


def test_report_contains_required_audit_sections_and_denominators() -> None:
    report = render_markdown_report(_complete_run())

    for heading in (
        "分类定义",
        "检测方法",
        "覆盖率与指标分母",
        "失败项",
        "漏检",
        "误报",
        "人工复审摘要",
        "误判原因",
        "实验性建议",
        "局限性",
        "模型与运行元数据",
        "AI 工具使用情况",
    ):
        assert heading in report
    assert "20 条记录" in report
    assert "2 条正常记录" in report
    assert "baseline" in report


def test_unavailable_sections_are_marked_unavailable_not_invented() -> None:
    inputs = replace(_complete_run(), evaluation=None, feedback=None, suggestions=None)
    report = render_markdown_report(inputs)

    assert report.count("尚未生成") >= 3
    assert "baseline" not in report


def test_markdown_fence_escapes_html_and_exceeds_longest_backtick_run() -> None:
    fenced = markdown_fence("a ````` b <script>")

    assert fenced.startswith("``````text\n")
    assert "&lt;script&gt;" in fenced


def test_reporting_service_uses_an_exact_allowlist_and_rejects_tampered_exports() -> None:
    service = ReportingService()
    exports = service.build_exports(_complete_run())

    assert service.source_for("predictions.json") == "model_prediction"
    assert service.source_for("report.md") == "markdown_report"
    with pytest.raises(KeyError):
        service.source_for("../task4_replies.json")
    service.validate_export(exports.predictions)
    exports.predictions["run_id"] = "tampered"
    with pytest.raises(InvalidExportArtifact):
        service.validate_export(exports.predictions)
