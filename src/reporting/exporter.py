from __future__ import annotations

from dataclasses import dataclass
import html
import json
import re
from typing import Any

from src.domain.hashing import content_hash


@dataclass(frozen=True, slots=True)
class ExportInputs:
    predictions: dict[str, Any]
    evaluation: dict[str, Any] | None
    feedback: dict[str, Any] | None
    suggestions: dict[str, Any] | None
    classification_definitions: dict[str, str]
    ai_tool_usage: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExportBundle:
    predictions: dict[str, Any]
    evaluation: dict[str, Any] | None
    feedback: dict[str, Any] | None
    suggestions: dict[str, Any] | None


def _with_hash(data: dict[str, Any], source: str) -> dict[str, Any]:
    value = {**data, "schema_version": "1.0", "source": source}
    value.pop("artifact_hash", None)
    value["artifact_hash"] = content_hash(value, frozenset({"artifact_hash"}))
    return value


def export_predictions(predictions: dict[str, Any]) -> dict[str, Any]:
    return _with_hash(predictions, "model_prediction")


def export_evaluation(evaluation: dict[str, Any]) -> dict[str, Any]:
    return _with_hash(evaluation, "official_ground_truth")


def export_feedback(feedback: dict[str, Any]) -> dict[str, Any]:
    return _with_hash(feedback, "human_revision")


def export_suggestions(suggestions: dict[str, Any]) -> dict[str, Any]:
    return _with_hash(suggestions, "experimental_suggestion")


def build_all_exports(inputs: ExportInputs) -> ExportBundle:
    return ExportBundle(
        predictions=export_predictions(inputs.predictions),
        evaluation=None if inputs.evaluation is None else export_evaluation(inputs.evaluation),
        feedback=None if inputs.feedback is None else export_feedback(inputs.feedback),
        suggestions=None if inputs.suggestions is None else export_suggestions(inputs.suggestions),
    )


def markdown_fence(value: str) -> str:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", value)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{html.escape(value)}\n{fence}"


def _safe_json(value: object) -> str:
    return markdown_fence(json.dumps(value, ensure_ascii=False, indent=2))


def render_markdown_report(inputs: ExportInputs) -> str:
    lines: list[str] = ["# 客服幻觉检测审计报告", ""]
    lines += ["## 分类定义", ""]
    for name, detail in inputs.classification_definitions.items():
        lines.append(f"- {html.escape(name)}: {html.escape(detail)}")
    lines += [
        "",
        "## 检测方法",
        "",
        (
            "baseline 三阶段检测：声明抽取、证据判断、完整性检查。"
            if inputs.evaluation is not None
            else "三阶段检测：声明抽取、证据判断、完整性检查。"
        ),
        "",
        "## 覆盖率与指标分母",
        "",
    ]
    if inputs.evaluation is None:
        lines.append("尚未生成官方评测。")
    else:
        coverage = inputs.evaluation.get("coverage", {})
        precision = inputs.evaluation.get("precision", {})
        lines.append(f"覆盖率: {coverage.get('numerator')}/{coverage.get('denominator')}")
        lines.append(f"Precision 分母: {precision.get('denominator')}")
    lines += ["", "## 失败项", ""]
    for item in inputs.predictions.get("results", []):
        if item.get("kind") == "failure":
            lines.append(f"- {item.get('id')}: {html.escape(str(item.get('error_summary', '')))}")
        elif "user_text" in item:
            lines.append(markdown_fence(str(item["user_text"])))
    lines += ["", "## 漏检", ""]
    lines.append(
        "尚未生成"
        if inputs.evaluation is None
        else _safe_json(inputs.evaluation.get("false_negative_ids", []))
    )
    lines += ["", "## 误报", ""]
    lines.append(
        "尚未生成"
        if inputs.evaluation is None
        else _safe_json(inputs.evaluation.get("false_positive_ids", []))
    )
    lines += ["", "## 人工复审摘要", ""]
    if inputs.feedback is None:
        lines.append("尚未生成人工复审。")
    else:
        lines.append(
            f"{inputs.feedback.get('reviewed_success_count')}/{inputs.feedback.get('total_success_count')}"
        )
    lines += ["", "## 误判原因", ""]
    if inputs.suggestions is None:
        lines.append("尚未生成误判原因。")
    else:
        lines.append(_safe_json(inputs.suggestions.get("analyses", [])))
    lines += ["", "## 实验性建议", ""]
    if inputs.suggestions is None:
        lines.append("尚未生成实验性建议。")
    else:
        lines.append(inputs.suggestions.get("warning", "小样本实验性建议，不代表效果提升"))
        lines.append(_safe_json(inputs.suggestions.get("suggestions", [])))
    lines += [
        "",
        "## 局限性",
        "",
        "当前基准只有 20 条记录，其中 2 条正常记录；闭集数据不能证明生产泛化能力。",
        "",
        "## 模型与运行元数据",
        "",
        f"run_id: {inputs.predictions.get('run_id', 'unknown')}",
        "",
        "## AI 工具使用情况",
        "",
    ]
    lines.extend(f"- {html.escape(item)}" for item in inputs.ai_tool_usage)
    report = "\n".join(lines)
    forbidden = ("validated", "improved", "upgrade", "out-of-fold", "full-data replay")
    if any(term in report.lower() for term in forbidden):
        raise ValueError("report contains forbidden suggestion-effectiveness wording")
    return report
