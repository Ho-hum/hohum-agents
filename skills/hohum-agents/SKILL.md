---
name: hohum-agents
description: >-
  Use for M-level or L-level multi-file software development, architecture design,
  independent cross-model code review, or large-codebase exploration.
  Enforces S/M/L routing, file-based handoffs (.agent/), hardened CLI delegation,
  3-round fix caps, 5 human-in-the-loop red lines, and long-term anti-rot guardrails.
  Skip for trivial S-level edits (1-2 known files, small change).
---

# hohum-agents: Multi-Agent Development Workflow

You are **Lead**. Your objective is to balance **design quality, code maintainability, and token efficiency** via a star-topology 4+2 role architecture.

Read [contracts-and-guardrails.md](./references/contracts-and-guardrails.md) before starting any L-level task or when hitting a failure/red line.

---

## 1. S / M / L Task Routing

| Level | Criteria | Path |
| :--- | :--- | :--- |
| **S (Small)** | 1–2 known files, tiny change, no schema/contract impact | Lead edits directly → run `verify:fast` → deliver (0 subagents) |
| **M (Medium)** | Needs exploration, 3–10 files, or non-trivial logic/UI | Scout (only if large repo) → Design Advisor if UI → brief (≤10 lines) → Builder → `verify:fast` → Checker → fix & retest |
| **L (Large)** | Cross-module, 0→1 feature, touches schema/public contract/architecture, or high ambiguity | Clarify → 2–3 approaches → `design.md` + context-free **Builder check** + human sign-off on interfaces/schemas → `plan.md` (slices ≤~400 lines) → per-slice loop (`Builder → verify:fast → pack_diff → Checker → fix ≤3 → ledger`) → `verify:full` → final whole-branch **Checker** → deliver + all `Ruling:` entries |

---

## 2. Role Delegation & Hardened Scripts

Customize role-to-model routing in `scripts/roles.local.json` (copied from `scripts/roles.example.json`, git-ignored). Never hardcode machine-specific paths in prompts.

1. **Smoke-test runners**:
   `python ./scripts/delegate.py --smoke-test`
2. **Pack review diff** (record `BASE = git rev-parse HEAD` before Builder starts):
   `python ./scripts/pack_diff.py --cwd <repo> --base <BASE> --head HEAD --out .agent/tasks/task-N-review.diff`
3. **Dispatch or resume external worker**:
   `python ./scripts/delegate.py --role <role> --cwd <repo> --prompt-file <file> [--session-id <id>]`

Available default role keys: `scout`, `builder`, `builder-mech`, `checker`, `checker-fallback`, `tech-advisor`, `builder-escalation`. Use host-native read-only subagents when staying within the same provider.

---

## 3. File-Based Handoffs

Keep `.agent/` in `.gitignore` (ephemeral per feature) and long-term architecture truth in `AGENTS.md` (≤150 lines) + `docs/ARCHITECTURE.md` + `docs/glossary.md` (project ubiquitous language: Term / Definition / Aliases to avoid; created by Lead when an M/L project designs core data models for the first time) + `docs/adr/`:

```text
.agent/
├── design.md          # User's words vs. Lead's assumptions kept separate
├── design-spec.md     # UI/UX tokens & interaction spec (Design Advisor)
├── assets/            # Visual assets
├── plan.md            # Slices (<=400 lines), global constraints, acceptance, file ownership
├── ledger.md          # Task status / Ruling: <decision> — <why> — <cost if wrong> / deferred minors
├── tasks/
│   ├── task-N-brief.md
│   ├── task-N-report.md
│   └── task-N-review.diff
├── findings/
└── logs/              # All raw CLI jsonl & verbose test logs (never paste into Lead context)
```

**Dispatch Brief Rule (5 items only in prompt)**: (1) one-line task context, (2) path to `task-N-brief.md`, (3) interfaces settled by prior slices not in brief, (4) explicit ambiguity rulings, (5) `task-N-report.md` path + short return contract. Never paste prior-task history.

---

## 4. Core Execution Discipline

- **Pre-coding (L-level)**: Read the repo before asking. Dependent questions one at a time; independent ones batched (≤3) or stated as explicit assumptions. Never default on the 6 non-defaultable items. Run a context-free **Builder check** on `design.md` before human sign-off. After a long design discussion is signed off into `design.md` and `plan.md`, remind the user they may run `/compact` in-place before starting slice execution to clear discussion noise and keep Lead in the smart zone.
- **Shift-left gates**: `verify:fast` (diff-scoped) MUST pass before invoking Checker. Gate retries count toward the **3-round quality cap**.
- **Fix loop (cap = 3)**: Rounds 1–2 resume the original Builder (`--session-id`); Round 3 dispatches `builder-escalation` with brief + report file; past Round 3, trip the breaker → Lead adjudicates (with `tech-advisor` if structural) and logs `Ruling:`. Re-reviews are strictly scoped to the fix diff. `Minor` items go to `ledger.md` as `deferred minor`.
- **Quota / 429 failure**: Treat as infra failure (does NOT consume the 3-round quality cap); switch at most once to a same-tier fallback. If unavailable, pause and inform the human—never silently downgrade Checker/Advisor or skip verification. Clean dirty Builder worktrees back to `BASE` before retrying.
- **Stop & ask human ONLY on the 5 red lines** (irreversible/destructive, security-sensitive, external side-effects, broken plan where every path is a guess, or touching persistent schemas/migrations, public contracts, guardrail configs, or new dependencies).
- **Post-L rough-run retro (optional, proposal-only)**: Only after a bumpy L-level run (hit the 3-round breaker, repeated environment friction, or heavy navigation detours), before cleaning `.agent/`, review `.agent/ledger.md`, failed `task-*-report.md`, and key `.agent/logs/` to output 3–5 prioritized repo-environment proposals (navigation hints, deterministic checks, mechanical rules, or `docs/glossary.md` entries). Never auto-edit guardrails/`AGENTS.md` or turn `AGENTS.md` into a verbose lessons log; apply only items approved by the human.
