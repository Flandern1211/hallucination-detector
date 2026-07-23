# 0110 客服回复幻觉检测 Dashboard 技术设计

- 日期：2026-07-22
- 状态：已按书面审阅修订，待再次确认
- 关联 PRD：[`../../requirements/2026-07-22-0110-customer-service-hallucination-detection-prd.md`](../../requirements/2026-07-22-0110-customer-service-hallucination-detection-prd.md)

## 1. 设计范围

本文只描述 0110 MVP 的技术实现设计，包括模块边界、数据契约、检测算法、评测隔离、实验性建议、错误处理和测试。产品目标、用户故事、业务分类、功能验收和路线图以关联 PRD 为准。

关键设计决策：

- Python `>=3.11`，FastAPI 作为唯一 HTTP 服务；
- Jinja2 服务端渲染、HTMX 局部交互和 ECharts 图表展示；
- HTMX 2.0.10 与 ECharts 5.5.1 固定版本并作为本地静态资源提供；
- 证据优先的三阶段检测：声明提取、逐声明核验、回答完整性检查；
- 运行时只注册真实 LLM Provider；抽象接口仅用于隔离具体 SDK 和注入测试 mock；
- 预测先冻结，之后才能载入人工标注；
- 每次运行可选择是否开启人工复审，运行开始后开关不可变；
- 原始预测、官方标注和人工修订使用独立模型与存储；
- 误判分析只生成不可执行、不可激活的实验性建议；
- MVP 不生成检测器候选、不执行双折验证、不修改只读基线配置、不激活或回滚版本；
- 所有 Python 依赖和工具配置统一写入根目录 `pyproject.toml`；
- 派生运行结果只写入根目录 `runtime/`，不引入数据库。

## 2. 系统上下文与数据流

```text
待检测 JSON
    │
    ▼
FastAPI 上传路由 ──> 数据校验器 ──失败──> Jinja2/HTMX 错误片段
    │
    ▼
检测编排器 ──> 声明提取 ──> 证据核验 ──> 完整性检查 ──> 结果聚合
    │                │             │              │
    └────────────────────── LLM Provider ─────────┘
    │
    ▼
冻结预测 ───────────────> Jinja2 结果页 / HTMX 片段 / 结果导出
    │                         │
    │                 [人工复审开启]
    │                         ▼
    │                 复审与修订管理器 ──> 人工修订快照 ──> 反馈验证器
    │                                                        │
    ├── 加载官方标注 ──> 官方评测引擎 ──> FN/FP 与指标 ───────┤
    │                                                        ▼
    └────────────────────────────────────────────── 实验性建议生成器
                                                            │
                                                            ▼
                                               建议 JSON / Markdown
```

官方标注只能进入官方评测和实验性建议流程；人工修订只能进入反馈验证和实验性建议流程。两者不得沿数据流返回首次检测，也不得在官方评测模块中混合。建议输出没有返回检测器配置或运行时依赖注入的路径。

## 3. 技术栈、代码结构与模块边界

### 3.1 依赖约束

根目录 `pyproject.toml` 是唯一依赖和工具配置来源：

| 依赖或工具 | 版本约束 | 用途 |
| --- | --- | --- |
| Python | `>=3.11` | 运行时 |
| FastAPI | `>=0.115,<1.0` | 唯一 HTTP 服务、路由和依赖注入 |
| Uvicorn | `>=0.34,<1.0` | ASGI 服务 |
| Pydantic | `>=2.10,<3.0` | 边界数据与配置校验 |
| Jinja2 | `>=3.1,<4.0` | 页面与 HTMX 片段模板 |
| HTMX | `2.0.10` | 页面局部更新，本地静态资源 |
| ECharts | `5.5.1` | 图表，本地静态资源 |
| pytest | `>=8,<10` | 自动测试 |
| Ruff | `>=0.9,<1.0` | lint 与格式检查 |
| mypy | `>=1.14,<2.0` | 静态类型检查 |
| build | `>=1.2,<2.0` | Python 制品构建 |

不得引入 Streamlit、第二个 HTTP 服务、数据库 ORM、任务队列或前端构建框架。HTMX 和 ECharts 文件随应用提供，页面不得引用 CDN。

vendored 静态资源目录必须同时保存上游许可证文本；`src/resources/vendor_hashes.json` 记录 HTMX/ECharts 文件的 SHA-256，构建测试在 wheel 安装后重新计算并比对，防止文件名版本与实际内容漂移。

MVP 不新增 LLM SDK 或第三方 HTTP 客户端。`LLMProvider` 使用 Python 标准库 `urllib.request` 发送非流式 HTTPS 请求，并在受限线程执行器中运行，避免阻塞 ASGI 事件循环。外部 Base URL 必须使用 HTTPS；仅 `localhost`、`127.0.0.1` 和 `[::1]` 可使用 HTTP。

新增未列出的运行时依赖或升级依赖主版本前必须取得用户确认；新增开发依赖必须在计划中说明用途和必要性。

`pyproject.toml` 的构建配置必须将 `src/api/templates/`、`src/api/static/` 和 `src/resources/` 纳入 wheel/sdist，并用构建产物测试验证安装后仍能渲染页面、提供固定版本静态资源并通过 `importlib.resources` 读取只读基线配置和风险参考。

### 3.2 代码结构

建议结构：

```text
src/
  api/
    app.py
    dependencies.py
    routes/
      pages.py
      runs.py
      reviews.py
      evaluations.py
      suggestions.py
      downloads.py
    schemas/
      requests.py
      responses.py
    templates/
      pages/
      fragments/
    static/
      css/app.css
      js/app.js
      vendor/htmx-2.0.10/htmx.min.js
      vendor/htmx-2.0.10/LICENSE.txt
      vendor/echarts-5.5.1/echarts.min.js
      vendor/echarts-5.5.1/LICENSE.txt
  application/
    run_service.py
    detection_service.py
    evaluation_service.py
    review_service.py
    suggestion_service.py
    reporting_service.py
  domain/
    models.py
    enums.py
    metrics.py
  input/
    loader.py
    validator.py
  detection/
    orchestrator.py
    claim_extractor.py
    evidence_judge.py
    completeness_checker.py
    aggregator.py
  providers/
    base.py
    llm_provider.py
  infrastructure/
    run_registry.py
    in_process_executor.py
    artifact_store.py
  evaluation/
    evaluator.py
    type_mapping.py
  review/
    revision_store.py
    diff.py
  suggestions/
    error_analyzer.py
    suggestion_generator.py
  reporting/
    exporter.py
  resources/
    __init__.py
    vendor_hashes.json
    detectors/
      baseline.json
    evaluation/
      task4_risk_reference.json
runtime/
  runs/
tests/
  unit/
  contract/
  isolation/
  integration/
  e2e/
```

约束：

- `src/api/app.py` 只创建 FastAPI 应用、注册路由和挂载静态资源。
- `src/api/` 只负责路由、请求校验、响应转换、模板渲染、静态文件挂载和依赖注入。
- JSON 路由、Jinja2 模板、HTMX 属性和浏览器 JavaScript 不得包含或复制检测、评测、实验性建议和复审规则。
- `application` 编排用例与状态转换边界，通过明确接口调用领域和基础设施模块。
- `domain` 不依赖 FastAPI、Jinja2、HTMX、ECharts 或具体 LLM SDK。
- `detection` 只依赖抽象推理接口，不直接读取环境变量。
- `evaluation` 只接收冻结预测和官方人工标注，不调用或修改检测器；人工修订不得传入 `evaluation/evaluator.py`。
- `review` 只基于冻结预测创建人工确认和修订，不拥有修改预测的接口。
- `suggestions` 只生成实验性建议；官方标签走评测模块，人工修订走建议模块内的反馈验证器，两者共享纯指标函数但不绕过标签隔离。该模块没有检测器配置写接口。
- `infrastructure/run_registry.py` 只保存当前进程的运行状态；`in_process_executor.py` 使用 `ThreadPoolExecutor(max_workers=1)` 调度外部任务；`artifact_store.py` 只在 `runtime/` 内执行经过校验和进程内互斥锁保护的原子写入。
- `src/resources/detectors/baseline.json` 是唯一只读检测器配置；运行时代码通过 `importlib.resources` 读取，不得创建、修改或选择其他检测器版本。
- `runtime/` 只保存设计允许的派生输出，不保存原始上传文件或密钥。

## 4. 领域模型与数据契约

必须使用 Pydantic 模型校验所有 HTTP、Provider、文件导入导出和运行时产物边界数据；领域内部纯函数可以使用不可变 dataclass 或 Pydantic 模型，但必须复用同一组不变量校验器。

### 4.1 契约版本与待检测记录

为兼容现有附件，待检测 JSON 和官方标注仍是无外层 wrapper 的数组，不要求 `schema_version`。所有运行快照和导出对象必须包含 `schema_version: Literal["1.0"]`。canonical JSON 固定使用 `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)` 的 UTF-8 字节，数组顺序保持不变；哈希使用 SHA-256 小写十六进制。时间统一使用带 `Z` 的 UTC ISO 8601。

任何对象携带自身哈希字段时，计算必须排除该字段本身：`RiskReference.content_hash` 排除 `content_hash`，快照/导出产物哈希排除各自的 `snapshot_hash` 或 `artifact_hash`。`source_prediction_hash` 对完整 `SuccessfulPrediction` 计算。修订事件的 `event_hash` 对排除 `event_hash`、但包含 `previous_event_hash` 的事件计算；首个事件的 `previous_event_hash=null`。验证器使用完全相同的函数，禁止各模块自行实现不同序列化规则。

```python
class ReplyRecord:
    id: str
    user_question: str
    system_reply: str
    knowledge_base: str
```

校验规则：

- 请求体最大 5 MiB，批次必须是包含 1 至 20 条记录的 JSON 数组，全部记录的 `user_question + system_reply + knowledge_base` Unicode 字符数合计不得超过 200,000；
- 四个字段必须存在且为字符串；
- 边界模型使用 `extra="forbid"`，未知顶层字段返回字段级 `422`，避免把未审查内容意外发送到外部服务；
- `id` 去除首尾空格后必须匹配 `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`，使其可安全作为 URL 段和逻辑键；问题和回复去除首尾空格后非空且分别不超过 10,000 个 Unicode 字符；知识库不超过 50,000 个 Unicode 字符；
- 批次内规范化后的 `id` 必须唯一，禁止 NUL 和除换行、回车、制表符之外的 C0 控制字符；
- 知识库可以为空，但运行创建响应必须返回闭集判断风险提示；
- 每条回复最多接受 10 个原子声明，超过上限整条失败，不静默截断。

只对 `id` 执行首尾空格去除并保存规范化值；问题、回复和知识库保留原始 Unicode 内容。输入哈希按输入顺序对“规范化 ID + 原始三个文本字段”的数组计算，不因 JSON 对象键顺序变化而变化。

### 4.2 原子声明、证据引用与遗漏

```python
class Claim:
    claim_id: str
    text: str
    source_quote: str
    source_start_offset: int
    source_end_offset: int
    kind: Literal["fact", "policy", "capability", "advice"]

class EvidenceReference:
    quote: str
    start_offset: int
    end_offset: int

class ClaimJudgement:
    claim: Claim
    verdict: Literal[
        "supported", "contradicted", "unsupported", "unverifiable"
    ]
    labels: list[HallucinationType]
    severity: Literal["高", "中", "低"] | None
    evidence: EvidenceReference | None
    core_relevance: Literal["high", "medium", "low"]
    reason: str

class OmissionFinding:
    omission_id: str
    missing_fact: str
    label: Literal["关键遗漏或歪曲"]
    severity: Literal["高", "中", "低"]
    evidence: EvidenceReference
    core_relevance: Literal["high", "medium", "low"]
    reason: str
```

声明和遗漏 ID 在单条记录内按输入出现顺序稳定生成，例如 `h01-c01` 和 `h01-o01`，必须唯一。声明按 `source_start_offset`、`source_end_offset`、模型返回顺序稳定排序后分配 ID。所有 offset 使用 Python 字符串的 Unicode code-point 索引，不使用 UTF-8 字节位置。

`Claim` 在进入核验前由本地代码验证 `0 <= source_start_offset < source_end_offset <= len(system_reply)` 且 `system_reply[source_start_offset:source_end_offset] == source_quote`。`ClaimJudgement.claim` 必须与传入核验器的 Claim 完全相等，模型不得重写声明来源。`EvidenceReference` 在进入聚合前验证 `0 <= start_offset < end_offset <= len(knowledge_base)` 且知识库切片与 `quote` 完全一致。任一校验失败是整条结构错误。

输出长度限制：声明文本和遗漏事实分别最多 5,000 和 2,000 个 Unicode 字符，单项 reason 最多 2,000，回复 summary 最多 4,000；所有字符串去除 NUL 和非法 C0 控制字符。超限属于结构错误，不截断。

声明级不变量：

- `supported`：`labels=[]`、`severity=null`、`evidence` 非空；
- `contradicted`：`labels` 非空、`severity` 非空、`evidence` 非空；
- `unsupported`：`labels` 非空、`severity` 非空、`evidence=null`；
- `unverifiable`：`labels=[]`、`severity=null`、`evidence=null`，并触发回复级人工复核；
- `labels` 去重后按统一类型固定顺序保存，禁止与 verdict 不一致的组合；
- 每个 `OmissionFinding` 必须有可验证知识库引用，且只表示回答中缺失、会实质改变用户判断的重要条件。

### 4.3 成功结果、失败结果与批次快照

模型输出和人工修订共享不含来源的分类主体：

```python
class ClassificationResult:
    is_hallucination: bool
    labels: list[HallucinationType]
    primary_type: HallucinationType | None
    severity: Literal["高", "中", "低"] | None
    review_required: bool
    claims: list[ClaimJudgement]
    omissions: list[OmissionFinding]
    summary: str

class SuccessfulPrediction:
    kind: Literal["success"]
    id: str
    result: ClassificationResult
    engine: Literal["llm"]
    model_name: str
    detector_version: str
    config_hash: str
    attempt_count: int

class FailedPrediction:
    kind: Literal["failure"]
    id: str
    error_code: Literal[
        "timeout", "rate_limited", "provider_error", "invalid_structure",
        "claim_limit_exceeded", "context_rejected", "request_budget_exhausted",
        "token_budget_exhausted", "provider_usage_missing", "cancelled",
        "run_deadline_exceeded"
    ]
    error_summary: str
    attempt_count: int
    model_name: str | None

PredictionResult = SuccessfulPrediction | FailedPrediction

class ProviderUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class BatchDetectionResult:
    schema_version: Literal["1.0"]
    results: list[PredictionResult]
    input_hash: str
    detector_config_hash: str
    network_attempt_count: int
    provider_usage: ProviderUsage
    stopped_reason: str | None
```

回复级聚合不变量：

- 任一声明包含幻觉标签或存在遗漏项时，`is_hallucination=true`；
- `labels` 是全部声明标签和遗漏标签的稳定去重并集；
- `is_hallucination=true` 时，`labels`、`primary_type` 和 `severity` 非空；正常结果三者分别为 `[]`、`null`、`null`；
- 只有 supported 声明且无遗漏时结果正常且 `review_required=false`；存在 unverifiable 声明时 `review_required=true`；零声明且零遗漏时结果正常但 `review_required=true`，避免把空分析当成已验证正常；
- `primary_type` 按风险、证据强度、`core_relevance`、声明或遗漏出现顺序、统一类型固定顺序确定；聚合器不得再调用 LLM；
- `FailedPrediction` 不含任何分类字段，不进入分类指标分母，也不能创建人工确认或修订。

`attempt_count` 是该记录真正发出的全部 Provider 网络请求次数，包括重试和结构修复；未发出请求即因运行预算、取消或 deadline 失败时为 `0`。批次级 `network_attempt_count` 必须等于所有记录尝试次数之和。

批次快照保存输入顺序稳定的 `list[PredictionResult]`、输入哈希、配置哈希、运行状态和冻结时间。失败记录不得被成功占位值替代。

### 4.4 运行配置、状态机与冻结语义

```python
class DetectionRunConfig:
    detector_version: Literal["baseline-v1"]
    manual_review_enabled: bool = False
    external_processing_acknowledged: Literal[True]

class RunState(str, Enum):
    created = "created"
    running = "running"
    retryable_partial = "retryable_partial"
    frozen = "frozen"
    abandoned = "abandoned"
```

合法状态转换：

```text
created -> running
running -> frozen                  # 全部成功，自动冻结
running -> retryable_partial       # 至少一条失败、用户取消或达到墙钟时限
running -> abandoned               # 执行器异常终止；进程退出后内存状态不恢复
retryable_partial -> running       # 只重试指定失败记录
retryable_partial -> frozen        # 用户接受失败并显式冻结
retryable_partial -> abandoned
```

检测生命周期与派生产物状态正交。运行还分别记录 `evaluation_status` 和 `suggestion_status`，取值为 `not_started | running | completed | failed`；二者只有在 `RunState.frozen` 时才能启动，不改变冻结状态。每个运行最多接受一个官方标注内容哈希和一个建议报告；相同请求幂等返回，不同标注哈希或第二次建议请求返回 `409`。

每个活动外部任务持有线程安全的 `cancel_event`、基于 `time.monotonic()` 的开始时间、墙钟 deadline、已发出网络尝试数和 Provider usage 累计值。检测 deadline 为 30 分钟，建议 deadline 为 5 分钟。取消是协作式的：不强制杀死正在执行的 `urllib` 调用；该调用最多等待 60 秒 timeout，返回后在下一次网络调用前检查取消、deadline、请求次数和 token 预算。检测任务取消或超时后保留已经完成的结果；当前正在处理但尚未形成完整结果的记录以及所有后续记录，按输入顺序生成 `cancelled` 或 `run_deadline_exceeded`，运行进入 `retryable_partial`。建议任务取消或超时后 `suggestion_status=failed`，不保存部分报告。

其他检测状态转换一律返回 `409`。运行一旦进入 `frozen`，预测列表、输入哈希和配置哈希不可改变。冻结后的“重试”创建带 `parent_run_id` 的新运行，只复制原始待检测输入和运行配置，不复制官方标注、评测、人工修订或建议。MVP 同时只允许一个活动的检测或建议外部任务；执行器忙时新任务返回 `409`。

### 4.5 人工修订

```python
class HumanReviewRevision:
    schema_version: Literal["1.0"]
    review_id: str
    run_id: str
    record_id: str
    status: Literal["confirmed_correct", "corrected"]
    source_prediction_hash: str
    reviewed_result: ClassificationResult
    changed_fields: list[str]
    revision_number: int
    save_request_id: str
    created_at_utc: datetime
    previous_event_hash: str | None
    event_hash: str
```

约束：

- `manual_review_enabled` 在创建运行时写入快照，检测开始后不可修改；
- 开关关闭或目标为失败记录时不得创建修订；
- `confirmed_correct` 的 `reviewed_result` 必须与原始分类主体结构等价；`corrected` 可修改分类主体并新增或删除声明、遗漏；
- 修订结果满足与成功预测相同的声明级、证据级和回复级不变量，但不携带 `engine="llm"`；
- `changed_fields`、`revision_number`、`previous_event_hash` 和 `event_hash` 均由服务端计算，不接受客户端指定；
- 每次保存创建递增版本，不更新或删除旧修订；相同 `save_request_id` 返回既有修订；
- 写入前在同一进程锁内校验原始预测哈希、当前最大修订号和结构，避免旧标签页覆盖；
- 反馈导出包含 `schema_version`、`run_id`、输入哈希、原始预测哈希、连续修订事件和事件链哈希。MVP 没有反馈导入服务或路由，导出文件只用于人工留档。

### 4.6 官方人工标注与风险参考

```python
class GroundTruthRecord:
    id: str
    is_hallucination: bool
    hallucination_type: str | None
    detail: str
    severity: Literal["高", "中", "低"] | None = None

class RiskReference:
    schema_version: Literal["1.0"]
    version: str
    source: Literal["uploaded_ground_truth", "frozen_benchmark_map"]
    ground_truth_hash: str
    risk_rule_version: str
    severity_by_positive_id: dict[str, Literal["高", "中", "低"]]
    content_hash: str
```

正常标注要求 `hallucination_type=null` 且 `severity=null`；幻觉标注要求非空类型和非空 `detail`。未知人工类型保留用于展示，但类型匹配指标对该记录标记不可映射。标注加载器不得向检测器暴露这些对象。

标注批次包含 1 至 20 条，`id` 使用与 ReplyRecord 相同的安全模式且批次内唯一；边界模型 `extra="forbid"`。`detail` 最长 10,000 个 Unicode 字符。标注 ID 与回复 ID 不要求完全相等，由评测器按第 8.1 节报告差集。

内置风险参考位于 `src/resources/evaluation/task4_risk_reference.json`，由开发前人工建立并只读交付；它必须恰好覆盖内置标注的全部幻觉正例，`ground_truth_hash` 必须匹配。上传标注只有在全部幻觉正例都带合法 severity 时才构建当前评测对象内的 `uploaded_ground_truth` 风险参考；部分提供时不补齐，高风险召回率返回 `null`。风险参考对象只在评测依赖图中创建，检测服务和聚合器的构造函数不得接收它。

### 4.7 只读基线检测器配置

`src/resources/detectors/baseline.json` 必须通过以下白名单契约：

```python
class BaselineDetectorConfig:
    schema_version: Literal["1.0"]
    version: Literal["baseline-v1"]
    claim_extraction_system_prompt: str
    evidence_judgement_system_prompt: str
    completeness_check_system_prompt: str
    error_analysis_system_prompt: str
    suggestion_system_prompt: str
    hallucination_type_definitions: dict[HallucinationType, str]
    severity_definitions: dict[Literal["高", "中", "低"], str]
    max_claims: Literal[10]
    temperature: Literal[0]
    provider_response_schema_version: Literal["1.0"]
```

五个 prompt 只包含固定系统指令，不包含数据占位符、模板表达式、条件执行、文件路径或网络地址；运行时数据由 Provider 作为独立 JSON user message 添加。加载时要求五类标签和三级风险定义键集合完全匹配，计算并记录配置哈希；校验失败时应用可以启动查看说明，但检测与建议按钮均禁用并显示无敏感值的配置错误。

## 5. 检测引擎

### 5.1 编排接口

```python
class DetectionEngine(Protocol):
    def detect_batch(
        self,
        records: list[ReplyRecord],
        detector: BaselineDetectorConfig,
        on_progress: Callable[[ProgressEvent], None] | None = None,
    ) -> BatchDetectionResult: ...
```

检测器逐条隔离异常。批次返回顺序与输入一致，禁止因异步或重试改变顺序。

一次记录检测最多包含 12 个逻辑调用：1 次声明提取、最多 10 次声明核验和 1 次完整性检查。每个逻辑调用最多 3 次常规网络尝试；若已收到响应但结构无效，可额外发起 1 次不重试的结构修复，因此单条理论最坏为 48 次网络请求尝试。每个检测运行的首次执行和冻结前重试共享 200 次网络请求尝试硬预算；每次真正发出 HTTP 请求前在锁内扣减，耗尽后当前及剩余记录按输入顺序生成 `request_budget_exhausted`，不再访问网络。

每次成功 Provider 响应必须返回 usage，应用在锁内累计 `total_tokens`。累计值在一次响应后达到或超过 250,000 时，不再发起后续请求并为尚未形成结果的记录生成 `token_budget_exhausted`。由于 usage 是响应后计量，最后一个已发出的请求可以使累计值突破 250,000 一次；这是断路器而非严格费用保证。缺少或非法 usage 时将当前记录及所有尚未形成结果的后续记录标为 `provider_usage_missing`，并立即停止本次检测的后续网络请求。页面显示逻辑调用上界、单条理论请求上界、运行请求硬预算、token 断路值和当前累计 usage。

### 5.2 第一阶段：声明提取

输入仅包含 `user_question` 与 `system_reply`。输出是最小可核验声明列表，每条声明同时包含规范化 `text` 和可精确回指 `system_reply` 的原文 quote/offset。

拆分规则：

- 一个声明只描述一个事实、政策、操作或高风险建议；
- 数值、时效、地址、产品参数和操作完成状态分别保留；
- 纯礼貌、道歉和无事实承诺的表达可以忽略；
- 不在此阶段读取人工标注。
- 输出为空是合法中间结果，但最终聚合必须触发人工复核；输出超过 10 条时整条记录失败。

### 5.3 第二阶段：证据核验

输入为原始问题、单个声明、知识库和统一分类定义。核验器必须先选择证据状态，再给标签和风险，避免直接凭整体印象分类。

对能力声明的特殊规则：

- 知识库明确写明系统未接入某能力时，声称“已查询”“已修改”“已升级”等判为 `contradicted` 和“能力越界”；
- 知识库没有能力信息，但回复确定声称已完成关键操作时，判为 `unsupported` 和“能力越界”；
- 仅建议用户自行操作时，不属于能力越界。

模型返回 EvidenceReference 后，应用在进入聚合前执行字符区间精确校验。`supported` 或 `contradicted` 缺少有效引用时不是 `unsupported`，而是结构错误；应用不得自行改变模型 verdict。

### 5.4 第三阶段：回答完整性检查

输入为原始问题、完整回复、知识库和“关键遗漏或歪曲”定义。该阶段不从回复提取已有声明，而是判断知识库中是否存在回答当前问题时必须说明、且遗漏会实质改变用户决定的重要条件。

约束：

- 只报告与用户问题直接相关的必要条件，不要求穷举知识库；
- 每个遗漏必须携带可本地验证的知识库引用、风险、相关度和理由；
- 没有关键遗漏时返回空列表；
- 不得把措辞优化、一般背景信息或知识库未包含的内容报告为遗漏；
- 不读取人工标注、风险参考或人工修订。

### 5.5 聚合

回复级标签为全部声明标签和遗漏标签去重后的稳定序列。主类型按以下键排序：

1. 风险：高 > 中 > 低；
2. 证据强度：`contradicted` > 带有效知识库引用的遗漏 > `unsupported`；
3. `core_relevance`：high > medium > low；
4. 声明或遗漏在结果中的稳定顺序；
5. 统一类型固定顺序，用于打破同一项含多个标签时的并列。

回复级风险取所有幻觉声明和遗漏项中的最高风险。

统一类型固定顺序为：知识冲突、无依据编造、能力越界、安全误导、关键遗漏或歪曲。该顺序只用于序列化和最终并列裁决，不覆盖风险、证据强度或相关度优先级。

## 6. 推理适配层

### 6.1 统一接口

```python
class DetectionInferenceProvider(Protocol):
    def extract_claims(...) -> list[Claim]: ...
    def judge_claim(...) -> ClaimJudgement: ...
    def find_omissions(...) -> list[OmissionFinding]: ...

class SuggestionInferenceProvider(Protocol):
    def analyze_errors(...) -> list[ErrorAnalysis]: ...
    def generate_suggestions(...) -> list[ExperimentalSuggestion]: ...
```

### 6.2 LLM Provider

运行时的同一个 `LLMProvider` 实现上述两个协议。配置来自环境变量：

- `HALLUCINATION_API_KEY`；
- `HALLUCINATION_BASE_URL`；
- `HALLUCINATION_MODEL`。

线协议固定为 OpenAI-compatible Chat Completions：

- `HALLUCINATION_BASE_URL` 表示 API 前缀，例如 `https://provider.example/v1`；去除末尾 `/` 后请求 `POST {base_url}/chat/completions`；
- 请求头为 `Authorization: Bearer <HALLUCINATION_API_KEY>`、`Content-Type: application/json`；
- 请求体包含 `model`、`messages`、`temperature: 0`、`stream: false`、`max_tokens: 2000`，以及 `response_format = {"type": "json_schema", "json_schema": {"name": operation_name, "strict": true, "schema": operation_schema}}`；`operation_name` 只能是 `extract_claims`、`judge_claim`、`find_omissions`、`analyze_errors` 或 `generate_suggestions`，`operation_schema` 分别由对应 Pydantic 输出模型生成；不发送未在本设计声明的采样或工具调用参数；
- Provider 必须返回 `choices[0].message.content` 中的 JSON 文本、顶层非空 `model`，以及非负整数 `usage.prompt_tokens`、`usage.completion_tokens`、`usage.total_tokens`，其中 `total_tokens >= prompt_tokens + completion_tokens`；不支持该契约视为配置不兼容，不实现厂商特有分支；
- 每个检测或建议任务以第一次成功响应的顶层 `model` 作为实际模型名；同一任务后续成功响应必须返回完全相同的值，否则视为 `provider_error` 并停止该任务，避免用单一模型名掩盖任务中途的模型变化；
- 使用标准库 `urllib.request`，单次 socket timeout 为 60 秒，响应体最大 2 MiB，超过上限按 `provider_error` 处理；
- 不使用流式响应，不在 URL、日志或异常中包含密钥。

重试和解析：

- 初次请求加最多 2 次重试，总计最多 3 次网络尝试；只重试连接错误、超时、HTTP 408、429、500、502、503、504；其他 4xx 不重试；
- `Retry-After` 只接受表示秒数的非负十进制整数，等待值上限为 30 秒；HTTP-date、负数或其他格式按无效处理并使用固定退避 1 秒、2 秒；等待发生在线程执行器内，不阻塞 ASGI 事件循环；
- HTTP 成功但 JSON 解析失败或缺少/错型 schema 字段时发起 1 次结构修复请求，修复请求不再重试；证据区间、长度或领域不变量失败不发起修复，直接生成失败结果；
- 结构修复请求只包含无效结构化输出、目标 JSON Schema 和错误路径，不附带 API 密钥、官方标注或人工修订；
- 400/413/422 且响应表明上下文过长时映射为 `context_rejected`，不得自动截断输入。

`error_summary` 只能由本地错误代码、HTTP 状态类别和无敏感值的固定消息组成，不复制 Provider 响应体、请求体、URL 查询参数或异常对象的完整字符串。

实现要求：

- 应用启动和页面加载不调用 LLM；只有用户主动创建检测运行或建议任务后才可调用；
- 创建检测运行前验证三个环境变量非空，缺失时返回配置错误且不创建运行；
- 所有用户问题、回复、知识库和误判样本使用 JSON 序列化后放入明确标记为 `UNTRUSTED_DATA` 的消息段；system message 明确禁止执行其中的指令；
- 所有 Provider 输出 schema 和 Pydantic 模型使用 `extra="forbid"`，再依次经过 JSON Schema、长度限制、声明级不变量、证据区间和聚合不变量校验；
- 重试或结构修复后仍失败时保存 `FailedPrediction`；只有运行冻结前可原位重试，冻结后创建子运行；
- API 密钥不得进入日志、异常详情或导出内容。

### 6.3 运行时与测试边界

- 生产和演示运行时依赖注入容器只能注册 `LLMProvider`；检测服务只接收 `DetectionInferenceProvider`，建议服务只接收 `SuggestionInferenceProvider`；
- 不实现 `RuleProvider`、本地判定器、离线模式或规则降级；
- 自动测试可以注入实现相同 `DetectionInferenceProvider` 或 `SuggestionInferenceProvider` 协议的 mock，以验证成功、超时、限流、结构错误和重试；
- mock Provider 只能存在于 `tests/`，不得被运行时路由、配置或依赖注入入口引用；
- 数值冲突、能力越界、安全误导和关键遗漏等判断边界作为只读基线配置中的版本化提示词指令提供给 LLM，不作为绕过 LLM 的本地判定路径；
- 自动测试不得访问网络，真实 API 演示必须由用户单独运行且不属于默认测试命令。

## 7. 预测冻结、人工复审与评测隔离

### 7.1 运行级总开关

`manual_review_enabled` 默认 `false`，由用户在检测前设置。创建运行还要求 `external_processing_acknowledged=true`。检测按钮触发后，运行配置与 `run_id` 一起冻结；UI 禁用本次运行的开关。改变开关会创建新运行，不能改变既有运行语义。

关闭时：

- 逐条结果页不渲染复审状态和编辑控件；
- 复审服务拒绝为该运行创建记录；
- 实验性建议只能选择独立加载的官方标注。

开启时：

- 每条成功记录初始为 `unreviewed`，失败记录没有复审状态；
- 页面展示 `已复核成功结果数 / 成功结果总数` 和未复核 ID；
- 用户可确认模型结果正确，或进入结构化编辑器修订；
- 未复核记录不等价于正确记录。

### 7.2 不可变预测与修订版本

一次检测运行只有在全部成功自动冻结，或用户对 `retryable_partial` 显式执行冻结后，才生成不可变预测快照。加载人工标注只会创建关联的评测对象，不修改预测。冻结前不得加载标注；冻结后任何检测重试创建新的子运行。

人工复审也不得修改预测快照。复审服务通过 `run_id + record_id` 读取原始预测，计算内容哈希并创建独立修订。后续编辑产生新的 `revision_number`；恢复原始结果同样生成新版本，不能删除历史。

结构化编辑器允许修改：

- `is_hallucination`、`labels`、`primary_type`、`severity`、`summary`；
- 规范化声明文本、可验证回复原文引用、证据判定、标签、风险、可验证知识库证据引用和理由；
- 关键遗漏文本、风险、可验证证据引用和理由；
- 新增漏检声明；
- 删除多检声明。

保存前重新运行证据区间、声明级和聚合不变量校验。页面以字段级差异展示原始预测、当前修订和上一修订。

### 7.3 三类标签来源与派生产物隔离

系统使用三个互不覆盖的标签来源，以及一种只读消费标签的派生产物：

- `model_prediction`：真实 LLM 首次输出；
- `official_ground_truth`：加载的官方标注；
- `human_revision`：本次 Dashboard 中人工确认或修改的分类主体；不携带 `engine="llm"`；
- `experimental_suggestion`：基于显式选择的单一标签来源生成的不可执行建议。

同一 ID 的官方标注与人工修订冲突时，页面展示差异。官方评测始终使用官方标注；建议分析批次必须显式选择一个主来源，禁止按有利于指标的方式逐条静默混合。

隔离控制：

- 检测函数签名不接受人工标注参数；
- 检测模块的构造函数和依赖注入图不接受 `GroundTruthRecord`、`RiskReference` 或 `HumanReviewRevision`；
- UI 在预测完成前禁用评测入口；
- 评测对象与检测对象使用不同类型和模块；
- 复审服务没有写预测快照的接口，修订必须带原始预测哈希；
- 集成测试捕获推理请求，断言其中不存在人工标注字段与内容；
- 运行导出同时记录预测哈希，证明评测前后预测未变化；
- 生成人工反馈导出和实验性建议前后同样校验预测哈希不变。

## 8. 评测实现

### 8.1 ID 对齐

评测器计算预测与标注 ID 的交集，并分别返回：

- `matched_ids`；
- `prediction_only_ids`；
- `ground_truth_only_ids`。

只有成功预测且 ID 匹配的记录进入指标。失败和未匹配项必须在报告中单列，不能默默丢弃。评测同时计算 `coverage = 成功且匹配数 / 人工标注数`；覆盖率低于 100% 时，所有指标标记为“不完整”。实验性建议仍可基于已有 FN/FP 生成，但必须继承“不完整”标记和固定警告。

### 8.2 指标

使用“存在幻觉”为正类：

- `precision = TP / (TP + FP)`；
- `recall = TP / (TP + FN)`；
- `f1 = 2PR / (P + R)`；
- 正常回复召回率，即 specificity：`TN / (TN + FP)`；
- `macro_f1`：正负两类 F1 的算术平均；
- `balanced_accuracy`：正类 Recall 与正常回复 Recall 的算术平均；
- 主类型匹配率：分母为人工标注为幻觉、模型也预测为幻觉且双方类型均可映射的记录，分子为预测 `primary_type` 落入人工类型兼容集合的记录；二分类 FN 不进入此辅助指标分母；
- 高风险召回率：分母为完整风险参考中的人工高风险幻觉记录，分子为其中被成功预测为幻觉的记录。

人工高风险集合来自与当前标注哈希精确匹配的完整 `RiskReference`，不得使用检测器自己的风险预测反向定义真值。风险参考缺失、不匹配或只覆盖部分幻觉正例时，高风险召回率返回 `null`，其他二分类指标不受影响。

分母为 0 时返回 `null` 并给出说明，不用 0 掩盖不可计算状态。

### 8.3 类型兼容

类型兼容表存放在版本化配置中：

| 人工标注类型 | 可兼容统一类型 |
| --- | --- |
| 政策编造、政策偏差、优惠编造、参数编造、信息编造 | 知识冲突、无依据编造 |
| 能力越界 | 能力越界 |
| 安全误导 | 安全误导 |
| 信息遗漏 | 关键遗漏或歪曲 |

兼容表不得根据单次评测结果自动改变。未知人工类型不报错丢弃：记录保留在二分类指标中，类型匹配指标将其标记为不可映射并排除分母，同时报告不可映射数量和原始类型。

## 9. 实验性建议实现

### 9.1 输入资格与来源隔离

输入为只读基线检测器元数据、冻结预测、用户明确选择的单一标签来源以及该来源下的 FN/FP。标签来源只能是：

- 已加载的官方标注；或
- 当前运行开启人工复审，且每条成功预测都有 `confirmed_correct` 或 `corrected` 最新修订、原始预测哈希全部匹配的人工修订快照。

`POST /runs/{run_id}/suggestions` 必须再次携带 `external_processing_acknowledged=true`；检测运行创建时的确认不自动授权后续把官方标注或人工修订材料发送给 LLM。

一次建议任务最多执行 2 个逻辑调用（误判归因、建议生成），沿用第 6.2 节每个逻辑调用最多 3 次常规尝试、1 次不重试结构修复和单响应 2,000 completion tokens 的规则，因此硬上限为 8 次网络请求尝试。Provider 计量的累计 `usage.total_tokens` 达到或超过 50,000 后停止；usage 缺失、5 分钟 deadline、用户取消或任一预算触发时任务失败，不生成部分建议。

官方标注与人工修订冲突时，页面先展示冲突，用户必须为整个分析批次选择一个来源。不得逐条混合。若所选来源下没有 FN 或 FP，返回 `409` 和“不存在可分析误判”，不创建建议任务且 Provider 调用数为 0。

应用按冻结预测的输入顺序为每个 FN/FP 生成仅在本次建议任务内有效的 `case_ref`（`case-001`、`case-002`……），并在内存中保存 `case_ref -> record_id` 映射用于页面关联。发送给 Provider 的建议请求只包含 `case_ref`，不得包含原始样本 ID；问题、回复、知识库片段、预测与所选标签作为带明确 `UNTRUSTED_DATA` 边界的分析材料发送。`case_ref -> record_id` 映射不得写入 Provider 输出或 `suggestion_report.json`；综合报告若需要展示原始记录 ID，只能由本地报告服务把评测来源与已校验的 `case_ref` 结果明确分栏合并。

### 9.2 误判归因

原因枚举：

- `claim_not_extracted`；
- `evidence_misread`；
- `unsupported_boundary_too_loose`；
- `unsupported_boundary_too_strict`；
- `capability_pattern_missed`；
- `partial_support_misclassified`；
- `critical_omission_boundary`；
- `non_factual_expression_false_positive`；
- `semantic_equivalence_or_negation_error`。

```python
ErrorReason = Literal[
    "claim_not_extracted", "evidence_misread",
    "unsupported_boundary_too_loose", "unsupported_boundary_too_strict",
    "capability_pattern_missed", "partial_support_misclassified",
    "critical_omission_boundary", "non_factual_expression_false_positive",
    "semantic_equivalence_or_negation_error",
]

class SuccessfulErrorAnalysis:
    kind: Literal["success"]
    case_ref: str
    error_kind: Literal["false_negative", "false_positive"]
    primary_reason: ErrorReason
    secondary_reasons: list[ErrorReason]
    evidence: str
    proposed_improvement: str

class FailedErrorAnalysis:
    kind: Literal["failure"]
    case_ref: str
    error_code: Literal[
        "timeout", "rate_limited", "provider_error", "invalid_structure",
        "request_budget_exhausted", "token_budget_exhausted",
        "provider_usage_missing", "cancelled", "run_deadline_exceeded"
    ]
    error_summary: str

ErrorAnalysis = SuccessfulErrorAnalysis | FailedErrorAnalysis
```

误判归因输出必须与输入 `case_ref` 集合完全相等、无重复，并保持输入顺序；每个成功项选择一个主原因，可附带去重的次原因、依据和对应改进建议。`evidence` 与 `proposed_improvement` 均为非空且最长 4,000 个 Unicode 字符。若 Provider 调用失败，或修复后的输出仍缺项、多项、重复、改写 `case_ref`、错误类型不一致或违反结构约束，应用为所有受影响 case 在 `run_metadata.json` 中保存本地生成的 `FailedErrorAnalysis`，将建议任务置为 `failed`，不调用建议生成、不保存 `SuggestionReport`，也不由本地规则伪造原因。

### 9.3 建议契约与白名单

```python
class ExperimentalSuggestion:
    suggestion_id: str
    category: Literal[
        "prompt_principle", "label_boundary", "generalized_example"
    ]
    target_stage: Literal[
        "claim_extraction", "evidence_judgement", "completeness_check"
    ]
    rationale: str
    proposed_change: str
    known_risks: list[str]

class SuggestionReport:
    schema_version: Literal["1.0"]
    run_id: str
    label_source: Literal["official_ground_truth", "human_revision"]
    input_hash: str
    prediction_hash: str
    detector_version: Literal["baseline-v1"]
    detector_config_hash: str
    model_name: str
    generated_at_utc: datetime
    coverage: float  # 0.0 <= coverage <= 1.0
    warning: Literal["小样本实验性建议，不代表效果提升"]
    analyses: list[SuccessfulErrorAnalysis]
    suggestions: list[ExperimentalSuggestion]
```

第二个逻辑调用只接收已校验的成功归因、只读基线元数据和标签来源，不再接收问题、回复、知识库、样本 ID 或 `case_ref -> record_id` 映射。Provider 只生成不含 `suggestion_id` 的建议主体；`suggestion_id`、报告级哈希、模型名、生成时间、覆盖率和固定警告均由服务端在校验通过后生成或绑定，不接受 Provider 或客户端覆盖。每条建议通过其所属 `SuggestionReport` 继承标签来源、哈希、实际模型名、基线版本、生成时间和固定警告，`target_stage` 即适用范围。

每份报告必须包含全部成功误判归因，且最多包含 20 条建议；`rationale` 和 `proposed_change` 各最多 4,000 个 Unicode 字符，`known_risks` 最多 10 项且每项最多 1,000 字符。超限时整份建议任务失败，不保存部分建议。

本地白名单校验器拒绝：

- 任一输入样本 ID；或在对输出与来源问题/回复执行 Unicode NFKC、转小写、合并空白后，连续复制任一来源文本 32 个或更多字符；
- 数值阈值、可执行代码、模板表达式、文件路径操作、网络请求或系统命令；
- 修改依赖、源码、只读基线配置、运行时 Provider 注册或输出契约的指令；
- 缺少适用阶段、理由或已知风险的建议；固定警告由服务端添加到报告，不是 Provider 可生成的建议字段。

建议只写入当前运行的 JSON 和 Markdown 产物。`SuggestionService` 没有写只读资源的依赖，也不存在检测器版本、活动指针、验证、激活或回滚接口。页面和导出禁止用 `validated`、`improved`、`upgrade`、`out-of-fold` 或 `full-data replay` 描述建议。

## 10. 运行时输出与原子写入

所有派生输出只能写入根目录 `runtime/`。原始上传文件只保留在当前进程内存，不写入 `runtime/`。目录布局：

```text
runtime/
  runs/<run_id>/
    run_metadata.json
    prediction_snapshot.json
    evaluation.json
    reviews/
      revisions.jsonl
      review_snapshot.json
    suggestions/
      suggestion_report.json
    reports/
```

`evaluation.json` 可以包含本次计算实际使用的规范化 `GroundTruthRecord` 字段、人工理由和标注内容哈希，以支持报告复核；它不得包含原始上传文件字节、未使用的额外字段或上传客户端路径。

`run_id`、`review_id`、`suggestion_id` 均由服务端生成固定格式的 UUID，不接受客户端路径片段。所有目标路径先 `resolve()`，验证仍位于对应 `runtime/runs/<run_id>/` 后才可访问。

除只追加的 `revisions.jsonl` 外，JSON 产物统一在目标目录创建临时文件、flush、`os.fsync`、关闭、完成结构校验后使用 `os.replace` 原子替换。`revisions.jsonl` 的“检查当前版本号—追加事件—flush/fsync—重建 snapshot”全过程由单应用 worker 内的 `threading.Lock` 保护；MVP 明确禁止多个应用 worker 或多个应用实例共享同一 `runtime/`。开发模式的 Uvicorn reload supervisor 可以存在，但任一时刻只能有一个提供服务的应用 worker。

`revisions.jsonl` 每个事件按第 4.1 节规则包含 `previous_event_hash` 和 `event_hash`；`review_snapshot.json` 是可重建派生视图。当前进程读取或导出复审历史时，若发现尾行截断，只忽略无法解析的最后一行并记录安全错误摘要，不修改更早事件。任一非尾部事件无法解析或哈希链不连续时，整个复审历史拒绝读取或导出。其他产物损坏时同样拒绝读取或导出，不猜测或自动选择替代文件；该校验不表示 MVP 支持进程重启后的运行恢复或历史页面。

MVP 不存在 `runtime/detectors/`、YAML 检测器文件或 `active.json`。唯一基线配置是打包进制品的 `src/resources/detectors/baseline.json`，运行时只读。

运行产物默认保留到用户手工删除 `runtime/` 中具体运行目录；MVP 不提供自动清理或删除 API。磁盘写入失败时保持内存中的运行状态、返回可执行错误提示，并不得声称产物已经持久化。

## 11. FastAPI HTTP 与页面设计

FastAPI 是唯一 HTTP 服务，直接提供完整页面、HTMX 片段、JSON API、上传、下载和静态资源。检测与建议生成在线程执行器的唯一 worker 中运行，不引入任务队列或第二服务；页面通过 HTMX 轮询进度片段，ASGI 事件循环不执行阻塞 Provider 调用或退避等待。进程重启会终止所有内存运行且不恢复任务或历史页面，UI 提示用户重新加载数据并创建新运行；已写入的派生产物保留在磁盘，但 MVP 不提供跨重启运行恢复或历史中心。

### 11.1 页面结构

使用服务端渲染的单页分区结构：

1. **运行配置**：数据加载、LLM 配置状态、输入规模、逻辑调用、网络尝试、token 与墙钟上界、外部处理确认、人工复审开关、启动和活动任务取消按钮；不提供本地或 mock 模式选择；
2. **检测总览**：关键数字、类型图和风险图；
3. **逐条结果**：筛选器、证据卡片和可选人工复审编辑器；
4. **评测中心**：标注加载、混淆矩阵、指标、FN/FP；
5. **建议中心**：误判归因、实验性建议、来源和固定警告；
6. **报告导出**：预测、评测、人工反馈、实验性建议和 Markdown 下载。

人工复审开启时，逐条卡片显示复核状态、差异、修订历史和恢复按钮，页面顶部显示复核进度。关闭时不创建复审组件和空反馈记录。

运行中的原始上传内容保存在进程内 `RunRegistry`，以 `run_id` 访问。预测、评测、人工修订、实验性建议和报告按第 10 节写入 `runtime/`。密钥只在 Provider 配置创建时从环境变量读取，不写入 `RunRegistry`、模板上下文或 HTTP 响应。

### 11.2 路由边界

| 方法与路径 | 职责 | 响应 |
| --- | --- | --- |
| `GET /` | 渲染主页面 | Jinja2 完整页面 |
| `POST /runs` | 校验上传、冻结运行配置并启动检测 | 运行摘要 HTMX 片段或 JSON |
| `GET /runs/{run_id}/progress` | 查询批次进度 | HTMX 进度片段或 JSON |
| `POST /runs/{run_id}/cancel` | 协作式取消当前检测或建议任务；没有活动任务时幂等返回当前状态 | 取消状态片段或 JSON |
| `GET /runs/{run_id}/results` | 展示过滤后的逐条结果 | Jinja2/HTMX 结果片段 |
| `POST /runs/{run_id}/retries/{record_id}` | 仅在 `retryable_partial` 状态重试失败项 | 进度片段或 JSON |
| `POST /runs/{run_id}/freeze` | 接受剩余失败并冻结快照 | 冻结摘要片段或 JSON |
| `POST /runs/{run_id}/child-retry` | 为已冻结运行创建不继承标签的新子运行 | 新运行摘要片段或 JSON |
| `GET /runs/{run_id}/reviews/{record_id}/edit` | 渲染结构化复审表单 | HTMX 表单片段 |
| `POST /runs/{run_id}/reviews/{record_id}` | 追加人工确认或修订 | 更新后的卡片与复核进度 |
| `POST /runs/{run_id}/ground-truth` | 校验并载入官方标注 | 标注摘要片段或 JSON |
| `POST /runs/{run_id}/evaluations` | 对冻结预测执行评测 | 指标与 FN/FP 片段或 JSON |
| `POST /runs/{run_id}/suggestions` | 基于显式单一标签来源生成实验性建议 | 建议与固定警告片段或 JSON |
| `GET /runs/{run_id}/downloads/{artifact}` | 下载允许的运行产物 | 文件响应 |

所有路由只调用 `application` 服务。路由不得计算指标、聚合标签、生成建议或操作运行产物。每个状态修改服务先验证第 4.4 节状态机；非法状态统一返回 `409`。

下载参数 `artifact` 只接受 `predictions.json`、`evaluation.json`、`feedback.json`、`suggestions.json` 和 `report.md`。它们分别映射到已校验的预测快照、评测结果、人工修订事件导出、建议报告和综合 Markdown；产物尚未生成时返回 `404`，其他值一律返回 `404`，不得把参数直接拼接为文件路径。

响应列明确写有“片段或 JSON”的路由采用固定协商规则：请求头 `HX-Request: true` 时返回 UTF-8 HTML 片段；否则仅在 `Accept` 包含 `application/json` 时返回 JSON；两者均不满足时返回 `406`。`HX-Request` 优先，错误响应使用相同格式。`GET /`、仅声明 HTML 的结果/复审路由和下载路由不参与该协商。浏览器 `app.js` 发起片段请求时必须显式发送 `HX-Request: true` 和 `Accept: text/html`。

为避免引入未经批准的 `python-multipart` 运行时依赖，待检测文件和官方标注文件由浏览器使用 `FileReader` 读取文本，再以 `application/json` 请求体发送。浏览器只负责 5 MiB 客户端预检查与传输，不改写业务字段；FastAPI 在 JSON 解析前依据 `Content-Length` 拒绝已知超限请求，并对解码后的内容再次执行完整校验。缺少或伪造 `Content-Length` 不能绕过解码后限制。

### 11.3 模板、HTMX 与图表

- 完整页面放在 `src/api/templates/pages/`，可替换片段放在 `src/api/templates/fragments/`；
- HTMX 2.0.10 从 `/static/vendor/htmx-2.0.10/htmx.min.js` 加载；
- ECharts 5.5.1 从 `/static/vendor/echarts-5.5.1/echarts.min.js` 加载；
- 页面不引用 CDN，不要求 Node.js 或前端构建流程；
- 因所有 POST 只接受 JSON 且不引入 `python-multipart`，`app.js` 将表单字段按固定请求 schema 序列化后用 `fetch` 发送 `application/json`，再调用 `htmx.swap` 更新服务端返回片段；浏览器不执行业务校验或字段修正；
- ECharts 只消费服务端计算后的图表数据，不在浏览器重新计算业务指标；
- Jinja2 环境保持 HTML 自动转义，模板不得对用户文本、知识库、模型输出或报告片段使用 `safe`；
- `app.js` 只处理图表初始化、无障碍状态和纯展示行为，不复制业务规则；插入文本使用 `textContent`，禁止将不可信文本传给 `innerHTML`、`insertAdjacentHTML` 或动态脚本执行 API。

### 11.4 本地 HTTP 信任边界

- 标准启动只绑定 Uvicorn 默认 loopback，文档明确禁止 `--host 0.0.0.0`、多 worker、反向代理暴露或局域网共享；
- 使用 `TrustedHostMiddleware`，只接受 `localhost`、`127.0.0.1` 和 `[::1]`；不安装或配置 CORS middleware；
- 所有 POST 请求必须为 `application/json`，并验证 `Origin`：浏览器提供 Origin 时必须与当前 loopback origin 完全一致；`Sec-Fetch-Site` 存在时不得为 `cross-site`；不满足时返回 `403`；
- 启动、取消、重试、冻结、复审、标注加载、评测和建议生成请求都携带一次性 `request_id`；应用服务在进程内保存结果以提供幂等重试，相同 ID 与不同请求体哈希冲突时返回 `409`；
- 这些措施只定义本地 MVP 信任边界，不替代生产认证。任何网络共享、部署或多人访问均需新设计。

## 12. 错误处理

| 场景 | 处理 |
| --- | --- |
| 输入 JSON 无效 | 阻止运行并显示字段路径或重复 ID |
| HTTP 资源不存在 | 返回 `404` 页面或 JSON 错误，不泄露内部路径 |
| 请求结构或上传内容无效 | 返回 `422` 及字段级 Jinja2/HTMX 错误片段或 JSON 错误 |
| 请求体、记录数、字符数或声明数超限 | 在后续 LLM 调用前返回 `413` 或字段级 `422`；不截断、不创建伪结果 |
| 外部处理未确认 | 返回 `422`，不创建运行、不调用 LLM |
| Host 或 Origin 不允许 | 返回 `400` 或 `403`，不执行状态修改 |
| LLM 环境变量缺失 | 禁止创建检测运行，返回 `503` 配置错误并列出缺失项 |
| Provider 不符合固定协议 | 返回 `503` 配置不兼容，不实现厂商特有静默降级 |
| API 超时或限流 | 最多重试 2 次，持续失败后标记该条失败，不执行本地降级 |
| LLM 结构无效 | 发起一次 LLM 结构修复；仍无效则标记该条失败 |
| 证据区间无效或声明超过 10 条 | 标记该条 `invalid_structure` 或 `claim_limit_exceeded`，不展示未验证证据 |
| 批次存在失败记录 | 进入 `retryable_partial`；冻结前可重试，显式冻结后评测标记覆盖率不足，后续重试只能创建子运行 |
| 执行器已有活动任务 | 返回 `409`，不排队、不启动第二个外部任务 |
| 用户取消或达到任务墙钟时限 | 当前 HTTP 调用最多等待既定 timeout；之后不再发起请求。检测保留已完成结果并进入 `retryable_partial`，建议任务失败且无部分报告 |
| 标注 ID 不匹配 | 评测交集并列出两侧差集 |
| 复审开关关闭时提交修订 | 拒绝请求，不创建反馈记录 |
| 修订结构与聚合规则冲突 | 定位具体字段并阻止保存 |
| 原始预测哈希不匹配 | 返回 `409`，拒绝保存并提示刷新当前记录 |
| 页面重跑或保存请求重试 | 相同 `save_request_id` 返回既有修订；新的主动修改才递增版本 |
| 官方标注与人工修订冲突 | 并列展示，要求明确选择来源 |
| 人工复审未覆盖全部成功结果 | 返回 `409`；允许导出已有反馈，禁止以人工修订生成建议 |
| 建议生成或白名单校验失败 | 保存失败摘要，不生成替代建议，不修改基线配置 |
| 冻结运行收到原位重试或预测写请求 | 返回 `409`；提示创建子运行 |
| 运行产物损坏或磁盘写入失败 | 拒绝加载或明确标记未持久化，不猜测回退、不声称已保存 |

错误日志不得包含 API 密钥或完整外部响应。面向用户的错误需说明受影响的记录与可执行的下一步。

## 13. 安全与数据处理

- 密钥只从环境变量读取；
- 服务只支持 loopback 和单应用 worker，不配置 CORS；状态修改请求执行 Host、Origin、Content-Type 和请求大小检查；
- 上传内容默认只存在当前进程内存，不将原始上传文件写入 `runtime/`；
- 用户主动导出的文件写入下载响应，不自动上传外部存储；
- 每次检测或建议生成都要求当前请求显式确认外部处理；页面说明配置的 LLM 服务可能有独立保留、地域和合规政策；
- 检测 LLM 请求只包含当前待检测记录和只读检测配置；建议请求只包含当前冻结运行、显式选择的单一标签来源和分析 schema；
- 不可信文本使用 JSON 序列化和明确边界放入提示词，system message 禁止执行数据中的指令；模型输出不因“结构化模式”而被信任，仍执行全部本地白名单和不变量校验；
- 首次检测请求与人工标注之间存在类型和模块双重隔离；
- 风险参考只由评测服务加载，不进入检测服务依赖图；
- 人工修订只追加保存，不能覆盖或删除原始预测；
- 导出文件明确标记 `model_prediction`、`official_ground_truth`、`human_revision` 和 `experimental_suggestion`；
- 实验性建议经过字段和内容白名单校验，不存在配置写入或激活接口；
- 报告需记录实际模型、检测器版本、重试次数和失败摘要，但不记录密钥。
- Jinja2 保持自动转义并禁止对不可信文本使用 `safe`；浏览器禁止以 HTML API 插入不可信文本；Markdown 中的用户和模型原文只能放入动态代码围栏：围栏反引号数量至少为 3 且严格大于内容中最长连续反引号数量，其他不可信文本对 `&`、`<`、`>` 做实体转义，禁止原样输出 HTML；
- HTMX 和 ECharts 只从 FastAPI 挂载的本地静态目录加载，不允许运行时 CDN。
- 运行时代码不得修改源码、测试、只读基线配置、风险参考、`task4_replies.json`、`task4_ground_truth.json` 或其他基准输入；所有文件写入必须经路径解析确认目标位于 `runtime/` 内。
- 下载路由只接受白名单产物名，并在返回文件前验证解析后的绝对路径仍位于对应 `runtime/runs/<run_id>/` 目录。

## 14. 测试设计

除纯文档、无行为格式化、静态 HTML/CSS 视觉探索和无执行行为的声明式示例外，正式功能严格执行 RED-GREEN-REFACTOR：先写最小失败测试并确认失败原因，再写最小实现，通过后重构并重新运行相关测试。

### 14.1 单元测试

- `tests/unit/test_input_validation.py`：请求体、批次数、字段类型、空值、字符数、控制字符和重复 ID 的每个边界；
- `tests/unit/test_evidence_reference.py`：合法引用、越界、空区间和 quote 不匹配；
- `tests/unit/test_claim_invariants.py`：回复原文字符区间、声明稳定排序、核验前后 Claim 相等、四种 verdict 的全部允许/拒绝组合、10 声明上限和唯一 ID；
- `tests/unit/test_aggregation.py`：声明与遗漏聚合、零声明复核、风险/相关度/顺序/类型最终排序；
- `tests/unit/test_prediction_result.py`：成功与失败判别联合，失败结果不能出现分类字段；
- `tests/unit/test_run_state.py`：每条合法转换和所有非法转换，冻结后哈希不变，子运行不复制标签，取消/30 分钟 deadline 后进入 `retryable_partial`；
- `tests/unit/test_task_budget.py`：200 次请求硬预算、250,000/50,000 usage 断路器、最后一次响应仅可突破一次、30/5 分钟 monotonic deadline 和协作式取消；
- `tests/unit/test_metrics.py`：TP/FP/TN/FN、所有二分类指标、明确分母、零分母、失败与未知类型；
- `tests/unit/test_risk_reference.py`：内置哈希与正例全覆盖、上传 severity 全量/部分规则；
- `tests/unit/test_review_revision.py`：聚合与证据不变量、递增版本、幂等 ID、事件链和原始哈希；
- `tests/unit/test_suggestion_validator.py`：允许的三类建议，以及样本记忆、阈值、代码、模板、文件和网络载荷拒绝；
- `tests/unit/test_error_analysis.py`：主/次原因枚举、依据必填、`case_ref` 集合/顺序匹配和分析失败记录；
- `tests/unit/test_exporter.py`：四类来源、契约版本、固定警告、禁用效果措辞和安全 Markdown；
- `tests/unit/test_canonical_hash.py`：canonical JSON、SHA-256、字段顺序无关、内容变化敏感、自身哈希字段排除和修订事件链连续性；
- `tests/unit/test_baseline_config.py`：固定版本、完整标签/风险键、无模板代码和配置哈希；
- `tests/unit/test_application_boundaries.py`：应用服务不依赖 FastAPI 类型，建议服务没有配置写接口。

### 14.2 Provider 契约测试

`tests/contract/test_llm_provider.py` 使用本地伪 HTTP 传输和 mock 协议实现，不访问网络，验证：

- endpoint、Bearer 头、非流式请求、`temperature=0`、`max_tokens=2000`、五个固定 JSON Schema operation 名、顶层 model 和 usage 解析，以及同一任务模型名变化时停止；
- HTTP/传输错误重试白名单、1 秒/2 秒退避、`Retry-After` 30 秒上限和不可重试 4xx；
- 60 秒 timeout、2 MiB 响应上限、结构修复恰好最多一次且不重试；
- claims、judgement、omissions 和 suggestions 的合法/非法结构；
- 两次重试后生成独立失败结果且不产生替代预测；
- 检测运行累计第 200 次网络尝试后不再调用传输层，并按输入顺序生成预算耗尽失败；
- usage 缺失或非法时停止后续传输；累计 token 达到断路值后不再调用，且页面状态显示真实累计值；
- 提示词包含 `UNTRUSTED_DATA` 边界且不包含标注、风险参考或密钥；
- 运行时依赖注入只注册真实 `LLMProvider`，无法从页面、请求字段或公开 API 选择 mock 或本地模式。

### 14.3 隔离测试

- `tests/isolation/test_detection_label_isolation.py` 捕获首次检测请求和依赖图，断言不存在官方标注、风险参考、人工修订字段或内容；
- 加载标注前后预测哈希一致；
- 人工确认、修订和恢复操作前后预测哈希一致；
- 冻结后重试创建新子运行，原运行预测哈希一致且子运行没有标注、评测和修订；
- 复审关闭的运行无法创建任何反馈记录；
- 官方标注与人工修订冲突不会被静默合并；
- 建议请求不含样本 ID，`case_ref` 与误判集合精确对应；建议输出中的完整原文记忆、阈值和代码载荷被拒绝；无 FN/FP 时不调用 Provider；
- 建议生成前后 `src/resources/detectors/baseline.json` 内容哈希不变，`runtime/detectors` 和 `active.json` 不存在。
- `tests/isolation/test_read_only_assets.py` 断言运行服务没有修改源码、基准输入、基准标注、风险参考或只读基线配置的写路径。

### 14.4 集成与端到端测试

- `tests/integration/test_app.py`：FastAPI 应用工厂、静态资源挂载、单 worker 执行器和依赖注入；
- `tests/integration/test_routes.py`：页面、JSON、HTMX、重试、冻结、子运行、取消、评测、建议和下载契约及状态门禁；
- `tests/integration/test_local_security.py`：Host、Origin、Content-Type、5 MiB 上限、不配置 CORS、Jinja 自动转义和禁止不可信 HTML 插入；
- HTMX 2.0.10 与 ECharts 5.5.1 本地静态路由可访问，HTML 不含 CDN 地址；wheel 中的文件哈希与 `vendor_hashes.json` 一致且许可证文本存在；
- 路由只委托应用服务，不在模板或 JavaScript 中重复业务计算；
- 使用确定性 mock 的内置 20 条样例完成检测、遗漏检查、冻结、评测、实验性建议和导出；
- 开启人工复审后，20 条样例可逐条确认或结构化修改，并导出带连续事件链的反馈 JSON；
- 关闭人工复审后，页面不渲染复审控件且无复审数据；
- 合法上传文件走完整流程；
- 非法或超限文件、未确认外部处理在检测前被拒绝且 Provider 调用数为 0；
- 单条 Provider 失败不终止批次；
- 批次存在失败项时进入 `retryable_partial`，显式冻结后覆盖率不足且指标、建议均标记不完整；
- 第二个外部任务启动请求返回 `409`，进度轮询仍可响应；
- 活动检测取消后当前 HTTP 调用最多完成一次，尚未形成完整结果的当前记录及后续记录标为 `cancelled`；使用假时钟验证 30/5 分钟 deadline，不进行真实等待；
- 下载产物名白名单、路径越界拒绝，以及 `HX-Request` 优先于 JSON `Accept` 的固定响应协商规则；
- FastAPI 应用可通过 `python -m uvicorn src.api.app:app --reload` 在 loopback 启动并完成 mock 核心交互；
- 导出指标与页面指标一致，Markdown 不包含用户提供的原始 HTML；
- 默认自动测试不调用真实外部 LLM。

### 14.5 标准验证命令

所有命令从仓库根目录运行：

```text
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m mypy src tests
python -m build
python -m uvicorn src.api.app:app --reload
```

交付前必须重新执行全部命令并报告最新退出码。项目尚未创建或依赖尚未安装时，结果必须标记为“尚不可运行”，不得声称通过。

## 15. 可观测性与可复现性

每次运行记录：

- `run_id`；
- `parent_run_id` 和状态转换时间线；
- 输入内容哈希；
- 只读检测器版本和配置哈希；
- Provider 和模型名；
- 开始、结束时间；
- 每条各阶段的逻辑调用数、网络尝试数、Provider usage、重试状态码类别和是否执行结构修复；
- 任务 deadline、是否由用户取消、取消请求时间和最终停止原因；
- 成功、失败数量；
- 人工复审开关状态、复核覆盖率和当前修订快照哈希。

建议报告额外包含标签来源、来源内容哈希、覆盖率、实际模型名、白名单校验结果和固定警告。真实 LLM 输出不承诺逐字确定性；系统通过输入哈希、只读配置哈希、模型名、`temperature=0`、重试信息和最终通过验证的结构化结果保证可审计，但不得表述为可重复得到相同预测。测试 mock 在相同输入下必须产生相同输出。

## 16. 兼容性与部署边界

- 待检测和官方标注数组保持现有无 wrapper 契约；运行快照和所有导出使用 `schema_version="1.0"`，其中人工反馈在 MVP 仅支持导出、不支持重新导入。同一主版本内只允许向后兼容的可选字段扩展；
- 破坏性字段变更必须引入新契约版本，并在实施前再次取得用户确认；
- MVP 不使用数据库，因此没有数据库迁移；
- HTMX 或 ECharts 升级必须显式修改固定版本、静态资源路径和测试，不得静默替换；
- 只读基线检测器配置、风险参考和类型兼容表各自版本化，不得根据单次评测或实验性建议静默改变；
- MVP 只支持 loopback、单应用 worker 运行，不支持网络部署、反向代理或共享 `runtime/`；
- MVP 不存在候选激活和回滚能力。未经用户明确确认，不执行部署、发布或真实外部 LLM 调用。

## 17. PRD 验收追踪矩阵

矩阵中的测试路径是实现时必须创建的验证目标。一个验收条目只有在对应自动测试通过，且涉及真实 LLM 的演示步骤由用户单独授权并记录结果时，才可标记完成。

| PRD 验收 ID | 设计规则 | 自动验证目标 |
| --- | --- | --- |
| SC-01 | 4.3 结果联合类型；6.2 重试；14.4 mock 全流程 | `tests/unit/test_prediction_result.py`、`tests/integration/test_app.py` |
| SC-02 | 4.2～4.3 证据、遗漏和聚合；5.2～5.5 三阶段检测 | `test_evidence_reference.py`、`test_claim_invariants.py`、`test_aggregation.py` |
| SC-03 | 8.1～8.3 ID 对齐、指标分母和类型兼容 | `tests/unit/test_metrics.py`、`test_risk_reference.py` |
| SC-04 | 4.4 状态机；7.2～7.3 冻结与隔离 | `test_run_state.py`、`tests/isolation/test_detection_label_isolation.py` |
| SC-05 | 4.4/5.1 任务预算与取消；9.3 建议白名单；11.4 本地边界；13 安全 | `test_task_budget.py`、`test_suggestion_validator.py`、`tests/integration/test_local_security.py` |
| AC-01.1 | 3.2、13：基准文件只读 | `tests/isolation/test_read_only_assets.py` |
| AC-01.2～AC-01.4 | 4.1：字段、批量、字符和请求体限制 | `tests/unit/test_input_validation.py`、`tests/integration/test_routes.py` |
| AC-01.5 | 11.2：只接受 JSON 文本上传 | `tests/integration/test_routes.py` |
| AC-02.1～AC-02.2 | 3.1、6.2：固定 Provider 协议和 URL 约束 | `tests/contract/test_llm_provider.py` |
| AC-02.3～AC-02.4 | 4.4、11.1：外部处理确认和调用上界 | `tests/integration/test_routes.py` |
| AC-02.5～AC-02.6 | 6.2～6.3、15：真实运行时注册和模型元数据 | `tests/contract/test_llm_provider.py`、`tests/integration/test_app.py` |
| AC-02.7～AC-02.11 | 4.1、4.4、5.1、6.2、11.2：声明上限、请求/token/时限预算、取消、失败重试和单任务执行 | `test_claim_invariants.py`、`test_task_budget.py`、`test_run_state.py`、`test_llm_provider.py`、`test_routes.py` |
| AC-03.1 | 4.3：成功结果契约和正常值语义 | `tests/unit/test_prediction_result.py` |
| AC-03.2～AC-03.4 | 4.2、5.2～5.4：声明原文锚定、知识库证据锚定和遗漏检查 | `test_claim_invariants.py`、`test_evidence_reference.py`、`test_aggregation.py`、`test_llm_provider.py` |
| AC-03.5～AC-03.6 | 8、11.1：筛选、总览和覆盖率 | `tests/integration/test_routes.py`、`tests/unit/test_metrics.py` |
| AC-04.1～AC-04.3 | 4.4～4.5、7.1：复审开关和成功结果分母 | `test_run_state.py`、`test_review_revision.py`、`test_routes.py` |
| AC-04.4～AC-04.8 | 4.5、7.2、10：不可变修订和恢复 | `tests/unit/test_review_revision.py`、`tests/isolation/test_detection_label_isolation.py` |
| AC-04.9 | 4.5、10、11.2：反馈事件链导出且不存在导入入口 | `test_review_revision.py`、`test_exporter.py`、`tests/integration/test_routes.py` |
| AC-05.1～AC-05.2 | 4.4、8.1：冻结门禁和 ID 集合 | `test_run_state.py`、`test_metrics.py`、`test_routes.py` |
| AC-05.3～AC-05.5 | 8.2～8.3：指标公式、分母、风险参考 | `tests/unit/test_metrics.py`、`test_risk_reference.py` |
| AC-05.6～AC-05.8 | 8.1～8.2、11.1：错误明细和不完整标记 | `test_metrics.py`、`tests/integration/test_routes.py` |
| AC-06.1～AC-06.4 | 9.2：原因枚举、依据和失败语义 | `tests/unit/test_error_analysis.py`、`tests/contract/test_llm_provider.py` |
| AC-07.1～AC-07.3 | 9.1、9.3：建议类别、只读输出和元数据 | `test_suggestion_validator.py`、`tests/integration/test_routes.py` |
| AC-07.4～AC-07.5 | 7.3、9.1：单一来源和复核覆盖率 | `tests/isolation/test_detection_label_isolation.py`、`test_review_revision.py` |
| AC-07.6～AC-07.7 | 6.2、9.3：不可信数据、记忆/代码拒绝和禁用措辞 | `test_llm_provider.py`、`test_suggestion_validator.py`、`test_exporter.py` |
| AC-08.1～AC-08.5 | 10、11.2、13：导出契约、来源区分和安全 Markdown | `tests/unit/test_exporter.py`、`tests/integration/test_routes.py` |
