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
| **L (Large)** | Cross-module, 0→1 feature, touches schema/public contract/architecture, or high ambiguity | Clarify → 2–3 approaches → `design.md` + context-free **Builder check** + human sign-off on interfaces/schemas → `plan.md` (slices ≤~400 lines) → **human confirmation of configured role models** → per-slice loop (`Builder → verify:fast → pack_diff → Checker → fix ≤3 → ledger`) → `verify:full` → final whole-branch **Checker** → deliver + all `Ruling:` entries |

---

## 2. Role Delegation & Hardened Scripts

Customize role-to-model routing in `scripts/roles.local.json` (copied from `scripts/roles.example.json`, git-ignored). Never hardcode machine-specific paths in prompts.

1. **Smoke-test runners, role models & target sandboxes** (before Slice 1):
   `python ./scripts/delegate.py --smoke-test --probe-sandboxes --cwd <repo>`
   Prints each role's configured model and probes temp-file write, default shell, and `esbuild` (when installed) in target sandboxes. Never auto-switches models on failure; pauses with suggestions for human decision.
2. **Pack review diff** (record `BASE = git rev-parse HEAD` before Builder starts; requires clean tree & non-empty committed diff bound to fixed SHAs):
   - Per-slice: `python ./scripts/pack_diff.py --cwd <repo> --base <BASE> --head HEAD --out .agent/tasks/task-N-review.diff [--verify-cmd "<cmd>" --verify-exit-code 0]`
   - Whole-branch final review: `python ./scripts/pack_diff.py --whole-branch --cwd <repo> --base <BRANCH_BASE> --head HEAD --dataflow "<input -> transform -> output>" --out .agent/tasks/final-branch-review.md [--verify-cmd "<cmd>" --verify-exit-code 0]`
3. **Dispatch or resume external worker**:
   `python ./scripts/delegate.py --role <role> --cwd <repo> --prompt-file <file> [--session-id <id>]`

Available default role keys: `scout`, `builder`, `builder-mech`, `checker`, `tech-advisor`, `design-advisor`, `builder-escalation`. No same-tier fallback roles are configured; if any configured model cannot work, pause and ask the human. Roles with `"runner": "host"` (default for `design-advisor`) run via host-native subagents and can be switched to `codex`/`dsh` in `roles.local.json` anytime.

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

- **Pre-coding & pre-execution confirmation (L-level)**: Read the repo before asking. Dependent questions one at a time; independent ones batched (≤3) or stated as explicit assumptions. Never default on the 6 non-defaultable items. Run a context-free **Builder check** on `design.md` before human sign-off. After sign-off on `design.md`/`plan.md` and **before executing Slice 1**, remind the user of each role's currently configured model (via `delegate.py --smoke-test`) and wait for confirmation (and note they may run `/compact` in-place before slice execution).
- **First UI slice & visual feedback**: Keep UI slices within the ~400-line budget; put a **thin runnable route + one end-to-end user path** into the **first UI slice** so right after it builds, the first preview verifies real production/static build, framework config drift (e.g. `tsconfig.json`), and desktop/mobile empty + filled states together (no separate preview harness or fixed polish slice). **Before running blind visual critiques or multi-round polish, always show those initial screenshots to the human and wait for explicit confirmation** (if direction is rejected, revise and re-shoot inside that slice). Drive visual rework by reproducible defects rather than uncalibrated numeric score loops; escalate rubric disagreement to the human, keep blind critics fresh, and reuse the fixer session.
- **Direct-edit re-tiering & fixed-SHA baseline**: Lead may run consecutive direct edits only within an already-confirmed presentational scope, tracked against the last reviewed **fixed SHA**; the moment cumulative diffs cross into dataflow, public contracts, or acceptance criteria, immediately re-tier into the corresponding M/L gate.
- **Shift-left gates & whole-branch review**: `verify:fast` (diff-scoped) MUST pass before invoking Checker; if a single sandboxed tool fails (e.g. `esbuild` `EPERM`), propose offloading only that failing check to the host while keeping working sandbox checks. For the final whole-branch review, always pack from the feature branch base with `pack_diff.py --whole-branch --dataflow ...` and require explicit Coverage Scope disclosure. Any code change from visual polish or whole-branch review MUST re-run `verify:full` (and re-check impacted areas) so the delivered commit is the exact verified green commit. Gate retries count toward the **3-round quality cap**.
- **Fix loop (cap = 3)**: Rounds 1–2 resume the original Builder (`--session-id`); Round 3 dispatches `builder-escalation` with brief + report file; past Round 3, trip the breaker → Lead adjudicates (with `tech-advisor` if structural) and logs `Ruling:`. Re-reviews are strictly scoped to the fix diff. `Minor` items go to `ledger.md` as `deferred minor`.
- **Model / quota / sandbox / 429 failure**: Treat as infra failure (does NOT consume the 3-round quality cap). **No same-tier fallback models exist — never auto-switch or downgrade any role.** Pause immediately, present the exact error and concrete options (e.g., wait for reset, switch to a human-approved model/role while keeping Builder and Checker on different providers, or host-offload only the failing check), and wait for the human's decision. Before retrying a failed Builder, discard only confirmed Builder-authored incomplete mutations (never revert `pre_existing_dirty` user edits).
- **Stop & ask human ONLY on the 5 red lines** (irreversible/destructive, security-sensitive, external side-effects, broken plan where every path is a guess, or touching persistent schemas/migrations, public contracts, guardrail configs, or new dependencies).
- **Post-L rough-run retro (optional, proposal-only)**: Only after a bumpy L-level run or milestone with repeated rework / evidence gaps (hit the 3-round breaker, repeated environment friction, or heavy navigation detours), before closing `.agent/`, review `.agent/ledger.md`, failed `task-*-report.md`, and key `.agent/logs/` to output 3–5 prioritized repo-environment proposals (navigation hints, deterministic checks, mechanical rules, or `docs/glossary.md` entries). Never auto-edit guardrails/`AGENTS.md` or turn `AGENTS.md` into a verbose lessons log; apply only items approved by the human.
