# hohum-agents

**English** | [简体中文](./README.zh-CN.md)

A model-agnostic **star-topology multi-agent development specification** and **hardened CLI delegation skill suite** built for medium-to-large, long-lived software projects.

**Core objective:** Establish a sustainable balance across **design quality, implementation quality, token efficiency, and long-term maintainability**, completely decoupled from specific LLM vendors or host ecosystems.

---

## Key Features

- **Lean 4 Core + 2 On-Demand Advisor Roles**: `Lead` (orchestrator), `Scout` (exploration), `Builder` (implementation), and `Checker` (independent verification), complemented by on-demand `Tech Advisor` and `Design Advisor`.
- **S / M / L Effort-Scaling Routing**: Zero subagent overhead for trivial S-level edits; mandatory design gates, context-free `Builder check`, and human sign-off on interfaces/schemas for complex L-level work.
- **Clear On-the-Loop Human Boundaries**: Clarify decisive unknowns (with sample/recipient intake and A/B/C throwaway Spike gate) while protecting **6 non-defaultable items**; confirm configured role models before Slice 1 and initial UI screenshots before visual polish; pause on **5 red lines** or any model/sandbox failure (no auto-switching fallbacks); disclose every autonomous `Ruling:` on handoff.
- **Long-Term Anti-Rot Guardrails**: Separate ephemeral `.agent/` handoffs from versioned `docs/` truth (including `docs/glossary.md` ubiquitous language), enforce diff-scoped gates, whole-branch final review packages (`--whole-branch`), guardrail config write-denial + `suppression` count ratchets, public-interface testing rules, triggered post-L environment retros, and phased static analysis.
- **Hardened Cross-CLI Bridge (Zero Third-Party Dependencies)**: Standard-library Python 3.10+ wrappers for structured JSONL parsing, `.agent/logs/` offloading, session resumption, pre/post `git status` read-only enforcement, and `--smoke-test --probe-sandboxes` target-sandbox diagnostics.

---

## Repository Layout

```text
hohum-agents/
├── README.md                            # English overview (default entry)
├── README.zh-CN.md                      # Simplified Chinese overview
├── docs/                                # Model-agnostic architecture specs (bilingual)
│   ├── en/                              # Full English specifications
│   │   ├── architecture.md              # Multi-Agent Development Architecture Spec
│   │   ├── human-in-the-loop.md         # Human-in-the-Loop & Clarification Spec
│   │   ├── fault-recovery.md            # Quota Exhaustion & Fault Recovery Runbook
│   │   └── references.md                # Section-by-Section Reference Index
│   └── zh-CN/                           # Full Simplified Chinese specifications
│       ├── architecture.md
│       ├── human-in-the-loop.md
│       ├── fault-recovery.md
│       └── references.md
├── skills/hohum-agents/                 # Portable multi-agent orchestration skill
│   ├── SKILL.md                         # Primary dispatch instructions (progressive disclosure)
│   ├── references/
│   │   └── contracts-and-guardrails.md  # Role contracts, red lines & recovery checklists
│   └── scripts/
│       ├── delegate.py                  # Hardened CLI bridge (Python 3.10+ stdlib only)
│       ├── pack_diff.py                 # Deterministic review diff packager
│       ├── roles.example.json           # Example role-to-model routing map
│       └── patches/                     # Example headless runner patch overlays
├── templates/codex-agents/              # Codex custom role TOML templates
└── tests/                               # Zero-external-model unit tests for scripts
```

---

## Quick Start

### 1. Install the Skill
Copy (or symlink) `skills/hohum-agents/` into your agent host's global or project skill directory, for example:
- Antigravity: `~/.gemini/config/skills/hohum-agents/`
- Claude Code: `~/.claude/skills/hohum-agents/`
- Project-scoped: `<repo>/.agents/skills/hohum-agents/`

### 2. Configure Local Model Routing (Git-Ignored)
Copy the example routing file into a local override (already listed in `.gitignore`) and map each role to your own subscriptions/APIs and reasoning tiers:

```bash
cp skills/hohum-agents/scripts/roles.example.json skills/hohum-agents/scripts/roles.local.json
```

If your runner binaries are not on global `PATH`, point to them via environment variables (e.g., `DSH_BIN`, `CODEX_BIN`), then run the smoke test from your workspace root:

```bash
python skills/hohum-agents/scripts/delegate.py --smoke-test
```

### 3. Run Repository Unit Tests (No External Models Required)

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

---

## Documentation

- [Architecture Specification](./docs/en/architecture.md) ([简体中文](./docs/zh-CN/architecture.md))
- [Human-in-the-Loop & Clarification Specification](./docs/en/human-in-the-loop.md) ([简体中文](./docs/zh-CN/human-in-the-loop.md))
- [Quota Exhaustion & Fault Recovery Runbook](./docs/en/fault-recovery.md) ([简体中文](./docs/zh-CN/fault-recovery.md))
- [Section-by-Section Reference Index](./docs/en/references.md) ([简体中文](./docs/zh-CN/references.md))

## License

[MIT](./LICENSE)
