# hohum-agents

[English](./README.md) | **简体中文**

面向中大型、需长期维护软件项目的**星形多 Agent 协同开发规范**与**硬化 CLI 调度 Skill 套件**。

核心目标：在 **设计质量、开发质量、Token 消耗、长期可维护性** 四者之间建立可持续的平衡，且规范本身与具体大模型、特定工具生态完全解耦。

---

## 核心特性

- **4 常驻 + 2 顾问精简角色体系**：`Lead`（主控）、`Scout`（侦察）、`Builder`（施工）、`Checker`（验收）+ 按需 `Tech Advisor`（技术顾问）与 `Design Advisor`（设计顾问）。
- **S / M / L 三级 Effort-Scaling 路由**：简单改动零子 Agent 开销，复杂任务强制过设计闸门与 `Builder check`。
- **人类在环（On-the-loop）清晰边界**：动工前按依赖关系澄清并守住 **6 类不可默认清单**；执行中连续推进、仅触发 **5 条红线** 才暂停；交付时全量公开 `Ruling:` 裁决清单。
- **长期防腐化护栏**：区分临时 `.agent/` 与长期 `docs/`（含 `docs/glossary.md` 领域统一语言表），实施 diff 级阻断、护栏拒写 + `suppression` 计数棘轮、公开接口测试约定、触发式环境复盘，并按项目阶段延迟引入重型静态检查。
- **硬化跨 CLI 桥接脚本（零第三方依赖）**：统一封装结构化 JSONL 解析、日志落盘 `.agent/logs/`、会话续接、只读工作区零改动校验与 `--smoke-test` 探活。

---

## 目录结构

```text
hohum-agents/
├── README.md                            # 英文总览（默认入口）
├── README.zh-CN.md                      # 简体中文总览
├── docs/                                # 通用、模型无关的完整架构规范（中英双语）
│   ├── en/                              # English specifications
│   │   ├── architecture.md
│   │   ├── human-in-the-loop.md
│   │   ├── fault-recovery.md
│   │   └── references.md
│   └── zh-CN/                           # 简体中文规范四件套
│       ├── architecture.md              # 多 Agent 协同开发架构规范（最终定稿）
│       ├── human-in-the-loop.md         # 人类介入与主动询问规范
│       ├── fault-recovery.md            # 额度耗尽与故障恢复推演手册
│       └── references.md                # 逐章参考来源索引
├── skills/hohum-agents/                 # 可移植的通用调度 Skill
│   ├── SKILL.md                         # 主调度指令（渐进披露）
│   ├── references/
│   │   └── contracts-and-guardrails.md  # 角色契约、红线与恢复细则
│   └── scripts/
│       ├── delegate.py                  # 硬化 CLI 桥接脚本（Python 3.10+ 标准库）
│       ├── pack_diff.py                 # 确定性 review diff 打包脚本
│       ├── roles.example.json           # 角色-模型路由示例配置
│       └── patches/                     # dsh 无头账号与模型补丁示例
├── templates/codex-agents/              # Codex 自定义角色 TOML 模板
└── tests/                               # 零外部模型依赖的脚本单元测试
```

---

## 快速开始

### 1. 安装 Skill
将 `skills/hohum-agents/` 复制（或软链接）到你所用 Agent 宿主的全局或项目技能目录，例如：
- Antigravity：`~/.gemini/config/skills/hohum-agents/`
- Claude Code：`~/.claude/skills/hohum-agents/`
- 项目级：`<repo>/.agents/skills/hohum-agents/`

### 2. 配置个人模型路由（不入库）
复制示例路由表为本地覆盖文件（已被 `.gitignore` 忽略），按你的实际订阅/API 调整各角色模型与思考档：

```bash
cp skills/hohum-agents/scripts/roles.example.json skills/hohum-agents/scripts/roles.local.json
```

若本机 CLI 不在全局 `PATH` 中，通过环境变量指定路径（例如 `DSH_BIN`、`CODEX_BIN`），并在工作区根目录运行探活冒烟测试：

```bash
python skills/hohum-agents/scripts/delegate.py --smoke-test
```

### 3. 运行本仓库单元测试（无需外部模型）

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

---

## 配套文档导航

- [架构规范正文](./docs/zh-CN/architecture.md)（[English](./docs/en/architecture.md)）
- [人类介入与主动询问规范](./docs/zh-CN/human-in-the-loop.md)（[English](./docs/en/human-in-the-loop.md)）
- [额度耗尽与故障恢复推演手册](./docs/zh-CN/fault-recovery.md)（[English](./docs/en/fault-recovery.md)）
- [逐章参考来源索引](./docs/zh-CN/references.md)（[English](./docs/en/references.md)）

## License

[MIT](./LICENSE)
