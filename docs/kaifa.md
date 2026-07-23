 ## 完整项目的具体流程

  ### 1. 先定义项目级约束

  在项目的 AGENTS.md 中写清楚：

  - 技术栈和最低版本
  - 测试、lint、build 命令
  - 禁止修改的目录
  - 代码风格和架构约束
  - 是否允许新增依赖
  - 数据库迁移、兼容性、部署和回滚要求
  - 哪些操作需要你的确认
  - TDD 是否存在明确例外

  Superpowers 明确规定：用户的直接要求和 AGENTS.md 优先级高于技能本身。因此项目特有规则不要只放在聊天里。版本说明 (https://github.com/obra/superpowers/blob/main/RELEASE-NOTES.md)

  ### 2. 使用 brainstorming 明确需求

  建议提示词：

  请使用 superpowers:brainstorming 处理这个项目。

  先检查当前仓库、文档和最近提交。
  如果项目包含多个独立子系统，先帮我拆分。
  在我批准设计之前不要写代码、安装依赖或创建脚手架。

  插件会：

  1. 检查代码库现状。
  2. 判断项目是否过大。
  3. 每次只问一个澄清问题。
  4. 明确目标、约束、成功标准。
  5. 给出 2～3 个实现方向及取舍。
  6. 分段提交架构、组件、数据流、异常处理和测试设计。
  7. 等你明确批准。

  “批准前禁止实现”是硬门槛，即使只是一个很小的功能也不会跳过。brainstorming 技能 (https://github.com/obra/superpowers/blob/main/skills/brainstorming/SKILL.md)

  对于完整项目，不要让它一次设计“前端 + 后端 + 支付 + 聊天 + 分析平台”。正确做法是拆成可以独立交付的子项目，例如：

  项目级目标和边界
  ├─ 账户与认证
  ├─ 核心业务 API
  ├─ 管理端
  ├─ 支付
  └─ 部署与可观测性

  每个子项目分别执行一次：

  spec → plan → implementation → verification

  ### 3. 审查并批准设计文档

  默认输出位置：

  docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md

  设计文档应该至少包含：

  - 范围与明确的非目标
  - 用户场景和验收标准
  - 架构与组件边界
  - 关键接口和数据模型
  - 错误处理
  - 安全与权限
  - 测试策略
  - 迁移、兼容和回滚方案
  - 尚未解决的问题

  Superpowers 会检查占位符、矛盾、歧义和范围过大问题，然后要求你审阅书面 spec。不要只在对话中说“差不多”；应真正打开文件检查，确认后再继续。

  ### 4. 建立隔离工作区

  设计批准后、正式执行前使用：

  请使用 superpowers:using-git-worktrees，
  为这个功能建立隔离工作区并验证测试基线。

  它会优先使用平台原生 worktree，否则退回 git worktree，然后：

  - 创建独立分支和目录
  - 安装或恢复项目依赖
  - 运行项目测试
  - 确认开始时的基线是干净的

  注意：

  - 如果当前已经位于 worktree，不应嵌套创建。
  - 创建 worktree 前插件应取得同意，除非 AGENTS.md 已声明偏好。
  - 项目内使用 .worktrees/ 时，必须确认它已被 .gitignore 忽略。
  - 如果基线测试本来就失败，不要让 Agent 把它们伪装成此次任务导致的问题；先记录并决定是否修复。worktree 技能
  (https://github.com/obra/superpowers/blob/main/skills/using-git-worktrees/SKILL.md)

  ### 5. 使用 writing-plans 生成实施计划

  提示词：

  设计已批准。请使用 superpowers:writing-plans，
  根据已批准的 spec 生成完整实施计划。
  计划中不得出现 TBD、TODO 或“适当处理”等占位描述。

  默认输出：

  docs/superpowers/plans/YYYY-MM-DD-<feature-name>.md

  合格计划应包含：

  - 每项任务涉及的准确文件路径
  - 文件的职责和接口
  - 要写的测试及测试代码
  - 运行命令
  - 预期失败或成功结果
  - 最小实现内容
  - 每个任务的提交点
  - 跨任务的全局约束

  每一步约为 2～5 分钟：

  写失败测试
  → 运行并确认以正确原因失败
  → 写最小实现
  → 运行并确认通过
  → 重构
  → 再次验证
  → 提交

  如果计划里出现以下内容，应退回重写：

  - “添加适当的异常处理”
  - “为上述功能编写测试”
  - “实现剩余逻辑”
  - “参考任务 2”
  - TODO、TBD
  - 不存在或没有定义过的函数、类型和接口

  writing-plans 规范 (https://github.com/obra/superpowers/blob/main/skills/writing-plans/SKILL.md)

  ### 6. 执行计划

  在支持多 Agent 的 Codex 中，优先使用：

  请使用 superpowers:subagent-driven-development
  执行这个计划。

  每个任务使用独立 implementer；
  每项任务结束后进行规格符合性和代码质量评审；
  Critical 和 Important 问题修复并复审后才能继续。
  除非遇到真正阻塞，不需要每项任务都询问我是否继续。

  标准循环是：

  主 Agent 读取计划
    ↓
  给一个全新 implementer 分配单项任务
    ↓
  implementer 实现、测试、提交、自查
    ↓
  独立 reviewer 检查 spec 符合性与代码质量
    ↓
  修复 Critical / Important 问题
    ↓
  复审通过
    ↓
  下一任务
    ↓
  最终进行整个分支的综合评审

  新 Agent 不应继承完整历史，而应收到精确、封闭的任务上下文。这能减少上下文污染，但也意味着计划中的接口、约束和文件路径必须完整。subagent-driven-development
  (https://github.com/obra/superpowers/blob/main/skills/subagent-driven-development/SKILL.md)

  没有多 Agent 能力时，才使用 executing-plans 顺序执行。

  ### 7. 严格执行 TDD

  Superpowers 的 TDD 非常强硬：

  没有先失败的测试，就不能写生产代码。

  完整循环：

  RED：写一个描述真实行为的最小测试
  → 确认它因为缺少目标功能而失败
  GREEN：只写使测试通过的最小代码
  → 运行相关测试和必要的回归测试
  REFACTOR：清理代码
  → 保持全绿

  测试一开始就通过，可能意味着：

  - 测试没有覆盖新行为
  - 功能已经存在
  - 测试写错了
  - mock 掩盖了真实行为

  不要把“写完代码后补测试”当成 TDD。TDD 技能 (https://github.com/obra/superpowers/blob/main/skills/test-driven-development/SKILL.md)

  对于视觉探索、纯配置、自动生成文件等不适合严格 TDD 的内容，最好提前在 spec 或 AGENTS.md 中明确例外；不要在执行到一半时临时绕过流程。

  ### 8. 遇到问题使用 systematic-debugging

  推荐提示词：

  当前出现测试失败。请使用 superpowers:systematic-debugging。
  在确定根因并提供证据前不要提出修复。

  它要求按四阶段执行：

  1. 根因调查：读完整错误、稳定复现、检查近期变更、追踪数据来源。
  2. 模式分析：寻找仓库内正常工作的相似实现，逐项比较差异。
  3. 假设验证：一次只提出一个假设，并用最小变化验证。
  4. 实施修复：先写失败的回归测试，再修根因。

  禁止连续堆叠多个猜测性改动。如果三次假设都失败，通常应重新检查架构或前提，而不是继续“碰运气”。systematic-debugging
  (https://github.com/obra/superpowers/blob/main/skills/systematic-debugging/SKILL.md)

  ### 9. 评审和验证

  每项任务后进行局部评审，重大功能完成后和合并前再做完整评审。

  评审结论分级：

  - Critical：立即修复，阻止继续。
  - Important：进入下一阶段前修复。
  - Minor：可以记录后处理。

  Reviewer 的意见也不是命令。应先对照当前代码、兼容性、测试和既有架构验证；错误建议需要用技术证据反驳。请求评审
  (https://github.com/obra/superpowers/blob/main/skills/requesting-code-review/SKILL.md)、处理评审意见
  (https://github.com/obra/superpowers/blob/main/skills/receiving-code-review/SKILL.md)

  完成前使用：

  请使用 superpowers:verification-before-completion，
  运行完整、最新的验证命令，并提供退出码和结果摘要。
  不要根据之前的测试结果宣布完成。

  至少应覆盖：

  单元测试
  集成测试
  端到端测试
  lint / format
  静态分析或类型检查
  构建
  数据库迁移验证
  安全扫描（适用时）
  原始 bug 的复现步骤
  逐项验收标准

  Superpowers 的原则是：Agent 的“已完成”报告不算证据，必须查看 diff，并重新运行完整验证命令。完成前验证
  (https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md)

  ### 10. 分支收尾

  最后使用：

  请使用 superpowers:finishing-a-development-branch 收尾。

  测试通过后，它会让你选择：

  1. 本地合并
  ## 可以直接使用的总提示词

  请使用 Superpowers 的完整工作流完成这个项目。

  2. 如果包含多个独立子系统，先拆成可独立交付的子项目。
  3. 在我批准设计前，不要写代码、安装依赖或创建脚手架。
  4. 将设计保存到 docs/superpowers/specs，并等待我审阅。
  7. 使用 subagent-driven-development 逐任务执行。
  8. 每项功能严格执行 RED-GREEN-REFACTOR。
  9. 每项任务后做规格符合性和代码质量评审。
  10. 遇到失败时使用 systematic-debugging，先查根因再修改。
  11. 完成前重新运行完整测试、lint、类型检查和构建。
  12. 对照 spec 逐项验收，不要仅凭子 Agent 报告宣布完成。
  13. 最后使用 finishing-a-development-branch，让我选择合并、PR、保留或丢弃。
  14. 不得擅自扩大范围、增加依赖、推送远端或执行部署。

  ## 最重要的注意点

  - Superpowers 的交付单位应是“可独立测试的子项目”，不是整个庞大平台的一份超长计划。
  - 设计和计划文档是核心产物，不是形式文件；后续 Agent 主要依赖它们获得上下文。
  - 不要边实现边偷偷改变需求。需求变化应返回 spec，更新并重新批准，再同步计划。
  - 只并行处理没有共享文件、状态和顺序依赖的任务；否则很容易产生冲突。
  - 它会增加前期对话、Token 和评审成本。小改动可以缩短设计，但不建议完全跳过设计和验证。
  - 可视化 brainstorming companion 会从项目方网站加载带插件版本的 logo；官方称不包含项目内容或点击数据。高隐私环境可以不启用该功能。遥测说明
  (https://github.com/obra/superpowers#visual-companion-telemetry)