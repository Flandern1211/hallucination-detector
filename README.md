# 客服回复幻觉检测

## 分类体系

系统将客服回复中的风险分为五类：

- **知识冲突**：回复与知识库中的政策、参数或事实相矛盾。
- **无依据编造**：知识库没有依据，却给出确定事实、优惠或结论。
- **能力越界**：系统没有对应接口或权限，却声称已经查询、修改、升级或执行操作。
- **安全误导**：涉及健康、资金、权益或安全时给出可能造成实际损害的错误建议。
- **关键遗漏或歪曲**：遗漏会改变用户决策的重要条件，或只保留部分事实导致错误理解。

严重程度按影响划分为高、中、低：高表示可能造成健康、资金、权益损失或虚假执行关键操作；中表示会明显误导业务判断；低表示影响有限但仍缺少可靠依据。一个样本可以有多个标签，主类型按风险优先级确定。

## 检测方法

FastAPI 提供唯一 HTTP 服务。检测流程为：

1. 从 system reply 中提取可回指的 claims；
2. 使用 OpenAI Chat Completions 兼容 Provider 判断 claim 与 knowledge base 的关系；
3. 独立执行关键遗漏检查；
4. 对 JSON 结构、verdict 字段组合、quote 和 Unicode code-point offset 做本地校验；
5. 每个逻辑调用最多进行 3 次网络尝试；证据无法唯一定位或字段不一致时记录结构失败，不伪造成功结果。

请求默认使用 OpenAI 兼容的 `response_format: {"type": "json_object"}`，不依赖 CDN，不把完整模型响应写入日志。

可通过环境变量选择真实模型或确定性离线 mock：

```powershell
$env:HALLUCINATION_API_KEY="mock-key"
$env:HALLUCINATION_BASE_URL="http://127.0.0.1:9"
$env:HALLUCINATION_MODEL="mock"
python -m uvicorn src.api.app:app --reload
```

## 检出率数据

已对 `task4_replies.json` 的 20 条回复执行确定性 mock 基线，并在预测冻结后加载独立的 `task4_ground_truth.json`：

| 指标 | 结果 |
|---|---:|
| TP / FP / TN / FN | 18 / 2 / 0 / 0 |
| Precision | 0.9000 |
| Recall | 1.0000 |
| F1 | 0.9474 |
| 漏检 | 无 |
| 误报 | h12、h16 |

mock 基线采用保守全阳性策略，因此召回率高，但会把与知识库一致的普通表达判为幻觉。h12、h16 的主要误判原因为 `non_factual_expression_false_positive`：检测边界过宽，没有先确认声明是否与知识库一致。建议仅在存在知识冲突、缺少必要依据或关键事实遗漏时输出阳性标签，并保留人工复核。

上述指标只用于证明检测、冻结、评测、误判分析和导出链路可执行，不代表真实模型效果或生产泛化能力。

## AI 工具使用情况

实现和验证使用 Codex 辅助需求拆解、代码检查、测试编写、接口验收和错误定位；检测支持 OpenAI 兼容 LLM，也提供不访问网络的 `mock-v1` 基线。API 密钥只从环境变量读取，不写入源码、README、日志或导出结果。

## 验证命令

```text
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m mypy src tests
python -m build
```

## 局限性

当前样本规模小且类别不平衡，不能据此宣称具备生产泛化能力。模型结构输出即使通过 JSON 校验，也可能出现语义边界错误；评测必须以冻结预测和独立官方标注为准。
