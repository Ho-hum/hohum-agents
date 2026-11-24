# 《多 Agent 协同开发架构规范》逐章参考来源索引

> **对应定稿**：[多 Agent 协同开发架构规范](./architecture.md)
> **可信度与性质标记**：
> - `✅ 一手核验`：经典公开原文或直接读取过开源仓库源码；
> - `⚠️ 检索摘要`：来自公开技术报道/论文检索摘要（引用其中的具体百分比或倍率数字前建议回查原文）；
> - `🔧 复审收敛`：在两轮独立批判审查中，针对原理论的过度工程化、反作用或条款冲突做出的本土化/实战裁剪。

---

## 一、对应正文「§1 架构总览与核心原则」

| 规范条目 | 主要参考来源 | 标记 | 采纳与裁剪说明 |
| :--- | :--- | :---: | :--- |
| **原则 1：以 Token 换质量 + Effort Scaling** | **Anthropic**《How we built our multi-agent research system》（主从架构效果提升 90.2%，但多 Agent 消耗约普通对话 15× Token；必须按任务规模动态缩放投入） | ✅ | 确立“多 Agent 不是省钱工具”的反常识认知，直接催生 §4 的 S/M/L 分级路由 |
| **原则 2：单写者原则（Single-Writer）** | **Cognition**（Walden Yan）《Don't Build Multi-Agents》及后续演进立场（每个动作隐含隐式决策，并行写代码易冲突；写操作保持单线程，子 Agent 优先贡献只读判断力）<br>**obra/superpowers** `subagent-driven-development/SKILL.md`（严禁并行派发多个实现子 Agent） | ✅ | 保留“读并行、写串行”铁律；仅放行文件归属完全正交的极少数场景 |
| **原则 3：高压缩比隔离（抗 Context Rot）** | **Anthropic**《Effective context engineering for AI agents》（长上下文诱发注意力衰减 Context Rot；子 Agent 在独立窗口消耗数万 Token，仅回传 1–2k 高信噪比摘要） | ✅ | 成为 §3 设定各角色回传 Token 预算（`≤ 800` / `≤ 1.5k`）的理论基石 |
| **原则 4：文件化交接与双层沉淀** | **Manus**《Context Engineering for AI Agents: Lessons from Building Manus》（把文件系统当作无限外部记忆，实现可恢复压缩）<br>**Anthropic**《Effective harnesses for long-running agents》（跨会话靠持久化文件交接，而非易失内存）<br>**obra/superpowers**（实测派发提示词粘贴历史高达 42k 字符且 99% 为冗余历史） | ✅ | 综合三方实践，形成 `.agent/` 临时交接 + `docs/` 长期资产的双层隔离 |
| **原则 5：按预期轮次而非单价选档** | **obra/superpowers** `SKILL.md`（“Turn count beats token price”：最便宜模型多步任务常多跑 2–3× 轮次，总成本反而更高）<br>**Aider** Architect/Editor 基准报告（规划与编辑能力拆分需有足够能力/价差才划算） | ✅ | 推翻“子 Agent 一律用最便宜模型”的直觉，为 Builder 制定文字 spec 与机械 spec 两档策略 |
| **原则 6：独立视角与客观验证** | **Anthropic**《Claude Code best practices》（“One writes, another reviews”对抗自评确认偏差）<br>**Anthropic** 长时应用开发 Harness（Planner / Generator / Evaluator 对抗式分离） | ✅ / ⚠️ | 结合批判审查修正了“绝对零上下文误伤合法约束”的风险，定为“零历史 ≠ 零需求” |
| **原则 7：不可逆边界机械化 + 复发即机械化** | **OpenAI**《Harness Engineering》（散文式 Prompt 长期必然漂移，须把反复违规转化为机械门禁）<br>**Martin Fowler / ThoughtWorks**（为非确定性 AI 建立确定性护栏） | ⚠️ / 🔧 | 经复审裁剪了大厂“全套重装上阵”的剂量，收敛为“Day 1 仅锁不可逆边界，其余同类问题第 2 次复发再机械化” |

---

## 二、对应正文「§2 三层配置架构」

| 规范条目 | 主要参考来源 | 标记 | 采纳与裁剪说明 |
| :--- | :--- | :---: | :--- |
| **第一层：禁止嵌套派发（最大深度 1 层）** | **obra/superpowers** `SKILL.md`（实测执行者私自拉起审查者会重复占用审查名额，明令 `no-subagents contract`）<br>主流 Agent 运行时（全局配置并发与最大嵌套深度上限） | ✅ | 写入全局硬规则，防止成本与流程失控 |
| **第二层：角色配置固化与前缀缓存稳定** | **Manus**《Context Engineering for AI Agents》（KV-Cache 命中率是 Agent 成本第一指标，提示词前缀必须稳定、只追加不改写）<br>现代声明式 Agent 配置规范（YAML frontmatter + 细粒度 `permissions` 沙箱） | ✅ | 将角色规范与硬权限锁死在第二层，既稳缓存又防只读角色越权 |
| **第三层：按需调度与执行解耦** | **Anthropic**《Building effective agents》与渐进式 Skill 加载实践（调度逻辑与角色细则解耦，避免无关对话加载重型工作流） | ✅ | 明确“调度层管何时派谁，角色层管怎么干活” |

---

## 三、对应正文「§3 角色体系与契约」

| 规范条目 | 主要参考来源 | 标记 | 采纳与裁剪说明 |
| :--- | :--- | :---: | :--- |
| **Lead（S/M 亲写，L 只协调）** | **Anthropic** Orchestrator-Worker 模式 + **obra/superpowers**（L 级主控不写代码以防污染上下文与绕过审查） | ✅ / 🔧 | 平衡日常效率与复杂项目洁净度：S/M 级减少跳数，L 级严格隔离 |
| **Scout（严格只读、带证据防假阴性）** | **Anthropic**《Effective context engineering》（只读探索与压缩回传）<br>社区模型分层探索实践 | ✅ / 🔧 | 复审补充“假阴性比误报更危险”，强制要求 `path:line` 片段证据与“未找到/不确定”显式标注 |
| **Builder（内层验证循环 + 4 种汇报状态）** | **obra/superpowers** `SKILL.md`（`DONE` / `DONE_WITH_CONCERNS` / `NEEDS_CONTEXT` / `BLOCKED` 四态契约与简短回报）<br>**UIUC Agentless**（修 Bug 先写复现测试） | ✅ / 🔧 | 经复审否决了独立设立 `Verifier` 角色（避免测试-修复高频循环放大 3 跳冷启动），将内层测试收归 Builder |
| **Checker（双项裁定 + 存疑核验 + 零历史≠零需求）** | **obra/superpowers**（`Spec compliance` + `Code quality` 双项必审、不得缺项、`⚠️ Cannot verify` 项）<br>**Anthropic** Claude Code Review 架构（增加独立核验层过滤误报 + 严重度分级）<br>**Anthropic** 长时应用 Harness（Evaluator 实操运行态应用做行为验证） | ✅ / ⚠️ | 结合三者优点，补齐“原文照抄全局约束”以防精简误砍合法兼容分支 |
| **Tech Advisor（按需顶级推理 + 带失败历史）** | **Anthropic** Advisor 策略（常规模型跑主循环，疑难或架构节点按需唤起顶级顾问）<br>**Cognition** “Smart Friend” 只读侧翼顾问模式 | ⚠️ / 🔧 | 经首轮复审明确**绝不与 Checker 合并**（上下文注入策略、调用频次与思维收敛/发散方向完全相反） |
| **Design Advisor（UI/UX 审美 + 生图 + 走查）** | **Anthropic** 长时应用 Harness（Evaluator 依据设计标准评审视觉品质）<br>DesignArena / WebDev 生态关于视觉审美与代码推理能力分离的实证 | ⚠️ / 🔧 | 与 Tech Advisor 在模型长板、工具权限（看图+生图）与触发时机上完全正交，拆为第二位按需顾问 |
| **人工介入第 1–4 条红线** | **obra/superpowers** `SKILL.md`（“Continuous execution & Rulings, not stalls”：仅不可逆/安全/外部副作用/计划彻底失效四类情况停下询问） | ✅ | 防止 Agent 频繁打断人类，同时守住安全底线 |
| **人工介入第 5 条红线（Schema/契约/护栏/依赖）** | **Martin Fowler / ThoughtWorks** 演化架构与数据迁移原则 + 供应链安全实践（Slopsquatting 防护） | 🔧 | 二次批判审查新增：代码重构已变便宜，但数据、对外契约与护栏篡改的代价依然不可逆 |
| **跨 Agent 通道 5 条抽象准则** | 现代编程 CLI 无头结构化输出、ACP/MCP 协议对比实践 | 🔧 | 二次复审收敛：正文保持工具解耦，仅定义能力准绳，具体通道方案入附录 B |

---

## 四、对应正文「§4 任务分级路由（S / M / L）」

| 规范条目 | 主要参考来源 | 标记 | 采纳与裁剪说明 |
| :--- | :--- | :---: | :--- |
| **S / M / L 三级 effort-scaling 路由** | **Anthropic**《How we built our multi-agent research system》（必须写明 Effort-Scaling Rules，防止琐碎任务过度派发）<br>**Anthropic**《Claude Code best practices》（`Explore → Plan → Code → Commit` 分阶段演进） | ✅ | 将“按规模控投入”落地为可判定的三档门槛，成为最大的一项 Token 节流阀 |

---

## 五、对应正文「§5 端到端工作流、确定性门禁与修复熔断」

| 规范条目 | 主要参考来源 | 标记 | 采纳与裁剪说明 |
| :--- | :--- | :---: | :--- |
| **设计关 4 步与需求澄清协议（先查后问 / 依赖单问 / 不可默认清单 / Builder check / Spike）** | **UC Berkeley MAST**《Why Do Multi-Agent LLM Systems Fail?》（arXiv 2503.13657：分析 1,600+ 轨迹，系统设计与规格问题约占失败的 42%，居首位）<br>**obra/superpowers** `brainstorming/SKILL.md`（先查后问、分段复述 Play It Back、开发者原话与假设分栏、Builder check 客观检验、一次性 Spike、opt-out 跳过出口）<br>**GitHub spec-kit** `templates/commands/clarify.md`（内部维度扫描不输出、Why it matters、原子覆盖更新、Deferred 泄压阀、`/analyze` 交叉一致性检查） | ✅ / ⚠️ / 🔧 | 把质量预算前置到动工之前；经源码核查与复审，删除了误读得来的“总量 ≤5 题硬上限”与形式主义“强制 EARS”，确立按“题间依赖关系”决定单问或打包，并新增 6 类“不可默认清单”防沉默同意 |
| **精简确定性门禁（`verify:fast/full` + `pack-diff` + 红灯禁入 Checker）** | **Stripe** Minions Blueprints（“系统驱动模型而非模型驱动系统”：确定性节点与 Agent 节点混排、本地 Shift-Left 校验、严格限制 CI 重试轮次）<br>**obra/superpowers** `scripts/review-package`（打包单文件 diff 避开主上下文） | ✅ / ⚠️ / 🔧 | 二次复审裁剪了重型私有脚本编排，仅保留 3 个不会变的哑节点，并把门禁重试纳入 3 轮总上限 |
| **按 diff 范围阻断** | 二次批判审查针对“Builder 文件归属边界”与全仓门禁冲突做出的架构裁决 | 🔧 | 解决全仓检查逼迫 Builder 越权改别处文件的结构性矛盾 |
| **统一 3 轮修复循环 + 升档 + 熔断 + 增量复审** | **obra/superpowers** `references/fix-loop.md`（原为 5 轮：1–3 轮续接原执行者，4–5 轮换高一档模型，超限熔断由主控裁决记账；复审只看修复增量 diff；Minor 不入循环） | ✅ / 🔧 | 面向日常研发将 5 轮压缩为 3 轮（2 轮续接 + 1 轮升档 → 熔断），降低等待与 Token 消耗 |
| **Checker 首审可核对防腐化清单** | **Sandi Metz** 经典软件工程原则（“Duplication is far cheaper than the wrong abstraction”，反伪 DRY）<br>**OpenAI**《Harness Engineering》& **ThoughtWorks** 护栏原则 | ✅ / 🔧 | 二次复审将空泛的“审抽象合理性”替换为 6 条可客观核对的清单，且严格限定仅在首审执行 |
| **不预设结论 & 禁自修（L 级）** | **obra/superpowers** `SKILL.md`（严禁提示词中写“do not flag”；主控自修会污染上下文并跳过审查） | ✅ | 防止主控为图省事把独立审查降级为橡皮图章 |

---

## 六、对应正文「§6 双层文档与文件化交接协议」

| 规范条目 | 主要参考来源 | 标记 | 采纳与裁剪说明 |
| :--- | :--- | :---: | :--- |
| **长期资产（`docs/adr/` + 精简 `AGENTS.md`）与临时目录（`.agent/`）分离** | **Anthropic**《Effective harnesses for long-running agents》（持久化 `feature_list` 与 `progress` 文件）<br>**GitHub spec-kit** & **Claude Code best practices**（根指令文件保持精简 ≤60–150 行防指令被忽略）<br>**OpenAI Codex / AGENTS.md 社区规范** | ✅ / 🔧 | 二次复审修补了“合入删除 `.agent/` 导致长期架构决策一并丢失”的漏洞；ADR 仅记难以逆转决策 |
| **黄金样板 + 遗留代码标记“禁止模仿”** | **OpenAI**《Harness Engineering》（指出 Agent 会模仿仓库既有坏模式导致腐化） | ⚠️ / 🔧 | 二次复审补齐“供给侧”对抗方案，用显式正例与反例隔离阻断负向 Few-shot |
| **最小 5 要素派发模板 + 账本 + 公开 `Ruling:` 清单** | **obra/superpowers** `SKILL.md` & `references/final-review.md`（用 `progress.md` 账本抵抗上下文压缩后重派已完成任务的惨痛故障；交付时全量列出 `Ruling:` 及判断错误的代价） | ✅ | 确保跨压缩不丢进度、杜绝 Agent 替人类做“秘密决定” |

---

## 七、对应正文「§7 Token 成本、质量防线与长期可维护性」

| 规范条目 | 主要参考来源 | 标记 | 采纳与裁剪说明 |
| :--- | :--- | :---: | :--- |
| **Token 控制：同类小改批处理 / 日志落盘 / 弃用网状团队** | **obra/superpowers** `references/batching.md`（同类小改合并单次派发）<br>**OpenAI Codex 社区验证卫生实践**（测试日志写本地忽略文件，仅回传退出码与失败切片）<br>**Anthropic** Agent Teams 文档（网状队友互聊约为单会话 7× Token，日常优先单会话或星形子 Agent） | ✅ / ⚠️ | 从源头砍掉日志刷屏、重复冷启动与网状闲聊三大隐形 Token 黑洞 |
| **数据模型与对外契约（只进不改 + Expand/Contract + 单一真相源）** | **Martin Fowler**《Evolutionary Database Design》经典重构与零停机迁移实践 | ✅ / 🔧 | 二次复审列为长期维护第一优先级杠杆 |
| **测试策略（公开接口测试、禁 mock 内部、真实 DB、特征测试、变异测试）** | **Michael Feathers**《Working Effectively with Legacy Code》（特征测试 Characterization Tests）<br>**Martin Fowler** 经典学派单元测试（Classical/Sociable Tests vs Mockist Tests）与变异测试（Stryker / mutmut）工程实践 | ✅ / 🔧 | 针对 AI 偏好写“脆弱 mock 单测”的通病，防止测试反过来锁死未来重构 |
| **护栏的护栏（拒写护栏配置 + `suppression` 计数棘轮 + 反例夹具）** | 针对 **OpenAI**《Harness Engineering》中“AI 编写自定义 Linter”的潜在 Goodhart 绕过风险所做的防御设计 | 🔧 | 二次复审核心增量：防止 AI 通过改配置或插 `eslint-disable` / `any` 悄然绕过门禁 |
| **对抗认知债（人定骨架、单 PR ≤400 行、复述验收）** | **Martin Fowler / ThoughtWorks** 2026 关于“认知债（Cognitive Debt）”与人类在环（On-the-loop）的论述<br>传统高效 Code Review 批量实证（单次审查超过 ~400 行后缺陷检出率断崖下降） | ✅ / ⚠️ / 🔧 | 把抽象的“人类在环”转化为三项可量化、可执行的验收动作 |

---

## 八、对应正文「§8 反模式清单」与「§9 渐进落地与调优」

| 规范条目 | 主要参考来源 | 标记 | 采纳与裁剪说明 |
| :--- | :--- | :---: | :--- |
| **反模式清单（10 条）** | 汇总 **obra/superpowers** `Common Rationalizations` 表格、**Cognition** 多写者失败分析、**Sandi Metz** 错误抽象警告，以及两轮独立复审暴露的新增反模式（如合并 Reviewer/Advisor、全仓阻断逼越界、mock 内部实现） | ✅ / 🔧 | 将高代价踩坑经验前置为明文禁令 |
| **“先查 Brief 与路由，再考虑升档”调优铁律** | **UC Berkeley MAST**（四成失败源于规格与编排而非纯模型智商）<br>社区 Multi-Agent 评估最佳实践（缺乏证据首先是 Briefing 问题而非模型问题） | ⚠️ / 🔧 | 避免一遇问题就无脑堆高价模型 |
| **变更扩散度传感器** | **ThoughtWorks** “Maintainability Sensors”（观测改小需求是否被迫触及越来越多文件，作为架构腐化早期信号） | ⚠️ | 经复审保留 `git log` 可客观计算的“变更扩散度”，降级噪声较大的“修复轮次”指标 |

---

## 九、对应正文「附录 A / B / C」

| 附录内容 | 主要参考来源 | 标记 | 采纳与裁剪说明 |
| :--- | :--- | :---: | :--- |
| **附录 A：三阶段护栏按触发信号引入表** | **OpenAI**《Harness Engineering》（分层约束、架构 Linter）<br>**GitClear** 代码重复度与 Churn 研究（重复代码块频次上升约 81% 的群体相关性数据）<br>现代静态生态（`dependency-cruiser` / `import-linter` / `ArchUnit` / `Knip` / `jscpd` / 变异测试） | ⚠️ / 🔧 | 二次复审按项目规模（Day 1 / >1万行 / >5万行）与触发信号分层，防止小项目 Day 1 过度工程化；并将 300 行硬上限修正为“单文件增长棘轮” |
| **附录 B：跨 Agent 协同通道选型参考** | 主流编程 CLI 无头结构化输出与沙箱文档<br>**Zed & JetBrains** Agent Client Protocol（ACP）规范与生态<br>**Anthropic** Model Context Protocol（MCP）规范与社区实践 | ✅ / ⚠️ / 🔧 | 二次复审纠正了把 CLI 桥接当“文本解析”的误判，确立“硬化 CLI 桥接”为默认跨厂商通道，将 ACP 定位于可选 UI 层，删除与本地编码无关的 A2A |
| **附录 C：触发式园艺熵减流程（G Mode）** | **OpenAI**《Harness Engineering》（Garbage Collection / Docs Gardening 周期性熵减代理） | ⚠️ / 🔧 | 二次复审将固定每周日历驱动改为“触发驱动”，并补齐“先有特征/契约测试覆盖”的前置安全红线与预算上限 |

---

## 十、主要参考资料清单

### 前沿团队工程文章
- **Anthropic**：*Building effective agents*（https://www.anthropic.com/research/building-effective-agents）
- **Anthropic**：*How we built our multi-agent research system*（https://www.anthropic.com/engineering/multi-agent-research-system）
- **Anthropic**：*Effective context engineering for AI agents*（https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents）
- **Anthropic**：*Effective harnesses for long-running agents*（https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents）
- **Anthropic**：*Claude Code best practices*（https://www.anthropic.com/engineering/claude-code-best-practices）
- **Anthropic**：长时应用开发 Harness（Planner/Generator/Evaluator）、Advisor 策略、Claude Code Review、Agent Teams 文档（⚠️ 检索摘要）
- **OpenAI**：*Harness Engineering*（2026，⚠️ 检索摘要）
- **Stripe**：*Minions: One-Shot End-to-End Coding Agents / Blueprints*（2026，⚠️ 检索摘要）
- **Cognition**：*Don't Build Multi-Agents*（https://cognition.ai/blog/dont-build-multi-agents）及后续单写者/只读侧翼演进分享
- **Manus**：*Context Engineering for AI Agents: Lessons from Building Manus*（https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus）
- **Martin Fowler / ThoughtWorks**：Agentic Engineering、认知债、Maintainability Sensors、Architectural Fitness Functions 与 Evolutionary Database Design 系列文章（https://martinfowler.com）

### 开源规范、协议与实证研究
- **obra/superpowers**：`subagent-driven-development` 源码（https://github.com/obra/superpowers）✅ 已直读源码
- **GitHub spec-kit**：Spec-Driven Development 工作流（https://github.com/github/spec-kit）
- **Zed & JetBrains**：Agent Client Protocol（https://agentclientprotocol.com）
- **UC Berkeley（MAST）**：*Why Do Multi-Agent LLM Systems Fail?*（arXiv:2503.13657）⚠️
- **UIUC（Agentless）**：*Agentless: Demystifying LLM-based Software Engineering Agents*（arXiv:2407.01489）
- **Aider**：*Separating code reasoning and editing*（https://aider.chat/2024/09/26/architect.html）
- **GitClear**：*AI Copilot Code Quality / Code Churn & Duplication Research*（⚠️ 检索摘要）
- **经典软件工程著作与原则**：Michael Feathers《Working Effectively with Legacy Code》、Sandi Metz《The Wrong Abstraction》

