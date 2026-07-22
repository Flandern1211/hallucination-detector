from enum import Enum


class HallucinationType(str, Enum):
    knowledge_conflict = "知识冲突"
    unsupported_fabrication = "无依据编造"
    capability_overreach = "能力越界"
    safety_misleading = "安全误导"
    critical_omission_or_distortion = "关键遗漏或歪曲"


class Severity(str, Enum):
    high = "高"
    medium = "中"
    low = "低"


class RunState(str, Enum):
    created = "created"
    running = "running"
    retryable_partial = "retryable_partial"
    frozen = "frozen"
    abandoned = "abandoned"


class ArtifactStatus(str, Enum):
    not_started = "not_started"
    running = "running"
    completed = "completed"
    failed = "failed"
