import pytest

from src.domain.models import ExperimentalSuggestionBody
from src.suggestions.validator import (
    UnsafeSuggestion,
    contains_source_memory,
    normalize_for_memory_check,
    validate_suggestions,
)


def _suggestion(proposed_change: str, **changes: object) -> ExperimentalSuggestionBody:
    body: dict[str, object] = {
        "category": "prompt_principle",
        "target_stage": "claim_extraction",
        "rationale": "使用保守、通用的判断原则",
        "proposed_change": proposed_change,
        "known_risks": ["可能增加人工复核数量"],
    }
    body.update(changes)
    return ExperimentalSuggestionBody.model_validate(body)


@pytest.mark.parametrize(
    "proposed_change",
    [
        "当置信度低于0.7时通过",
        "执行 `open('x').write(y)`",
        "请求 https://example.com",
        "修改 src/resources/detectors/baseline.json",
        "{{ user_question }}",
        "运行 powershell 写入配置",
        "安装 requests 依赖",
        "修改 Provider 注册和输出契约",
    ],
)
def test_rejects_threshold_code_network_path_template_and_mutation_payloads(
    proposed_change: str,
) -> None:
    with pytest.raises(UnsafeSuggestion):
        validate_suggestions([_suggestion(proposed_change)], ["source material"], {"h01"})


def test_rejects_sample_id_and_32_normalized_source_characters() -> None:
    source = "ＡＢＣ   " + "很长的客户原文" * 6
    copied = normalize_for_memory_check(source)[:32]

    with pytest.raises(UnsafeSuggestion):
        validate_suggestions([_suggestion("h01 " + copied)], [source], {"h01"})


def test_normalized_memory_check_allows_only_short_generalized_fragments() -> None:
    source = "ＡＢＣ   " + "很长的客户原文" * 6
    normalized = normalize_for_memory_check(source)
    assert contains_source_memory(normalized[:32], [source])
    assert not contains_source_memory(normalized[:31], [source])


@pytest.mark.parametrize(
    "term", ["validated", "improved", "upgrade", "out-of-fold", "full-data replay"]
)
def test_rejects_forbidden_effectiveness_terms(term: str) -> None:
    with pytest.raises(UnsafeSuggestion, match="effectiveness"):
        validate_suggestions([_suggestion(f"Use a {term} rule")], [], set())


def test_rejects_more_than_twenty_suggestions_as_one_report() -> None:
    with pytest.raises(UnsafeSuggestion, match="20"):
        validate_suggestions([_suggestion("使用抽象边界原则") for _ in range(21)], [], set())


def test_valid_generalized_suggestion_is_returned_without_redaction() -> None:
    suggestion = _suggestion("对缺少证据的确定性事实采用更保守的标签边界")

    assert validate_suggestions([suggestion], ["某个来源材料"], {"h01"}) == (suggestion,)
