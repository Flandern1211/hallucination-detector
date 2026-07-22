from __future__ import annotations

import re
import unicodedata

from src.domain.models import ExperimentalSuggestionBody


class UnsafeSuggestion(ValueError):
    pass


_FORBIDDEN_EFFECT = ("validated", "improved", "upgrade", "out-of-fold", "full-data replay")
_UNSAFE_PATTERNS = (
    re.compile(r"\d+\.\d+"),
    re.compile(r"`"),
    re.compile(r"https?://|www\.", re.I),
    re.compile(r"\{\{|\}\}|\{%|%\}"),
    re.compile(r"\bsrc[\\/]|[A-Za-z]:[\\/]|baseline\.json", re.I),
    re.compile(r"powershell|cmd|bash|python|open\(|write\(|安装|依赖|provider|输出契约|修改", re.I),
)


def normalize_for_memory_check(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).lower().split())


def contains_source_memory(candidate: str, sources: list[str], window: int = 32) -> bool:
    normalized_candidate = normalize_for_memory_check(candidate)
    for source in sources:
        normalized_source = normalize_for_memory_check(source)
        if len(normalized_source) < window:
            continue
        for start in range(len(normalized_source) - window + 1):
            if normalized_source[start : start + window] in normalized_candidate:
                return True
    return False


def validate_suggestions(
    suggestions: list[ExperimentalSuggestionBody],
    source_texts: list[str],
    source_ids: set[str],
) -> tuple[ExperimentalSuggestionBody, ...]:
    if len(suggestions) > 20:
        raise UnsafeSuggestion("suggestions must not exceed 20")
    for suggestion in suggestions:
        text = " ".join([suggestion.rationale, suggestion.proposed_change, *suggestion.known_risks])
        lowered = text.lower()
        if any(term in lowered for term in _FORBIDDEN_EFFECT):
            raise UnsafeSuggestion("effectiveness terms are not allowed")
        if any(record_id in text for record_id in source_ids):
            raise UnsafeSuggestion("sample ids are not allowed")
        if contains_source_memory(text, source_texts):
            raise UnsafeSuggestion("source memorization is not allowed")
        if any(pattern.search(text) for pattern in _UNSAFE_PATTERNS):
            raise UnsafeSuggestion("unsafe suggestion payload")
    return tuple(suggestions)
