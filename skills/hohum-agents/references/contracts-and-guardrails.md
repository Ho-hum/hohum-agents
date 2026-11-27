# Contracts, Guardrails & Recovery Reference

Read this reference before L-level design gates, when reviewing diffs, or when handling failures/red lines.

---

## 1. Clarification Elicitation & Six Non-Defaultable Items
Before asking, inspect the repo and invite the user to share **one redacted sample** or state in one sentence **"who receives the output and what they do next"**. For open questions that would actually change the architecture or contract, pick only the needed elicitation tool (reuse confirmed artifacts directly in `design.md` and tests—no mandatory multi-round forms, full combinatorial matrices, 3-example-per-rule tables, 4-state screen grids, or separate breadboard sign-offs):
- **Input-to-deliverable contrast**: ask concrete handoff cases (e.g., pure single-format vs. mixed inputs) when output shape alters data contracts.
- **Discriminating rule examples**: only for rules with two reasonable interpretations and different error costs, pair 1 contrasting pair to lock the boundary and fallback.
- **Shortest user path**: only when an interactive flow is unsettled, sketch the minimal path inline in the question (visual prominence and empty-state rendering are verified on the initial screenshot, not on paper).

Never bury these **six non-defaultable items** in an assumptions list; always obtain explicit human confirmation (if recommending an option, only recommend the conservative, reversible choice):
1. **Data irreversibility**: hard vs. soft delete, retention, overwrite vs. append, migration of existing data.
2. **Permission boundaries**: who can read/write, default-deny vs. default-allow.
3. **Public contracts & schema identity**: uniqueness constraints, ID semantics, external API/event formats.
4. **Billing / quota / PII / compliance**.
5. **Non-goals** (explicitly out of scope).
6. **Acceptance criteria** (quantify vague adjectives or state testable cases).

Stop clarifying when no decisive open question remains (list the rest under `Deferred`); >5 **solution-changing** open questions signals the task should be split. Offer an opt-out ("or say 'just build it'") if the user did not ask for brainstorming. When new preferences arise **after sign-off**, log the impacted contracts and acceptance items in `ledger.md` and re-review strictly scoped to that impact surface.

### Throwaway Spike Gate (Optional — Only When A + B + C All Hold)
1. **A (Changes architecture)**: List two plausible outcomes and which contract, dependency, or core interaction order each would change; if both lead to the same design, skip the Spike.
2. **B (Unresolved via right source)**: Verify technical facts via repo/official docs and intent via user/sample first; proceed only if still unresolved and an experiment can actually distinguish outcomes.
3. **C (Criterion & budget)**: Before coding, state 1 question, an X/Y decision rule, and a time cap (default 5–10 min) cheaper than building the first real slice (otherwise shrink the first slice and mark provisional contracts + reopen criteria in `design.md`); stop on answer, timeout, or ambiguity (log as unresolved).
4. **Authorization**: Pure local technical probes within existing permissions (e.g. verifying library behavior on a redacted sample) may run directly after logging a 2-line experiment card; ask the human first whenever user interaction, scope expansion, or extra budget is required.
5. **Containment & handoff**: Keep prototypes inside an ignored path (`.agent/prototype/`) or throwaway branch; **never import, copy, or merge prototype code into production**—Builders receive only the conclusions, evidence, and acceptance samples written into `design.md` (security, concurrency, and data contracts still go through normal pre-check and sign-off).

---

## 2. Five Human-in-the-Loop Red Lines
During execution, stop and ask the human **only** when hitting:
1. Irreversible or destructive operations.
2. Security-sensitive changes (auth, secrets, permission boundaries).
3. Side effects outside the current workspace (merge, push to shared branch, deploy/publish).
4. Severe plan failure where every path forward is a guess.
5. Changes to **persistent schemas/migrations**, **external public contracts**, **guardrail configs** (lint/type/arch/CI/thresholds/baselines), or **adding a new third-party dependency**.

**Pause Packet Format**: (1) which red line was hit, (2) 2 concrete options with trade-offs & reversibility, (3) your recommended option.

---

## 3. Builder Testing & Anti-Rot Rules
- Write/update tests through **public module interfaces** only; **never mock owned internal modules** (mock only external boundaries: third-party APIs, clock, RNG).
- Use real DB engines (embedded/container) rather than mock repositories.
- Add characterization/golden tests before refactoring legacy code.
- **Guardrail protection**: Never edit lint/tsconfig/arch/CI/suppression baselines; suppression counts (`eslint-disable`, `@ts-ignore`, `any`, `# type: ignore`, `noqa`, `skip`) may only decrease.
- Schema migrations are append-only (never edit applied migrations); breaking changes follow expand/contract.

---

## 4. Checker Initial-Review Anti-Rot Checklist (First Review Only)
Do NOT expand scoped re-reviews with this checklist. Default severity is `Minor`; escalate to `Important` if touching schema/contracts/guardrails/test-weakening:
- Bypassed existing repository primitives / golden exemplars?
- Introduced an unruled third-party dependency?
- Touched persistent schema / migrations / public contracts without human approval?
- Mocked owned internal modules or weakened existing test assertions?
- Modified guardrail configs or added suppressions?
- Introduced a flag-parameter wrong abstraction for premature DRY?
- If `docs/glossary.md` exists, introduced any listed "aliases to avoid" or drifted from canonical project domain terms?
- **Recurring defect (2nd+ time in repo)?** Explicitly propose promoting it to a mechanical lint/arch rule.

### Whole-Branch Final Review Contract
- Always generate the final review packet with `pack_diff.py --whole-branch --base <BRANCH_BASE> --head HEAD --dataflow "<flow>"` (never label a last-slice diff as whole-branch evidence).
- Checker must spot-check cross-slice contracts along the listed end-to-end dataflows in live repo files and explicitly report **Coverage Scope** (directly inspected vs. relied on via prior slice reviews/tests).

---

## 5. Pre-Execution Model Confirmation, Model/Sandbox Failure & Dirty Worktree Recovery
- **Pre-execution model confirmation**: After human sign-off on `design.md`/`plan.md` and **before dispatching Slice 1**, run `delegate.py --smoke-test` (with `--probe-sandboxes --cwd <repo>` for L-level) and display a concise table of each role's currently configured runner and model for explicit human confirmation.
- **No same-tier fallback — pause & advise**: Do **not** configure or auto-switch to same-tier fallback models for any role (`scout`, `builder`, `builder-mech`, `checker`, `tech-advisor`, `design-advisor`, `builder-escalation`). Whenever a model/runner hits quota/429, auth error, timeout, or sandbox failure (infra failures do NOT consume the 3-round quality cap), **pause immediately**, report the concrete failure and 2–3 actionable options with trade-offs (e.g., wait for quota reset, switch to a human-chosen role/model while keeping Builder and Checker on different providers, or offload only a failing sandboxed step like `esbuild` to the host), and wait for the human's decision.
- **Builder**: Before dispatching, record `pre_existing_dirty` (reported automatically by `delegate.py`). If pre-existing uncommitted files overlap the slice's file ownership, pause and ask the human or use an isolated worktree. On failure, inspect `git status` and `git diff` first: keep clean commits that passed `verify:fast`, discard only confirmed Builder-authored incomplete changes within slice ownership, and **never auto-revert pre-existing or unattributed user modifications**.
- **Lead**: New session reads `.agent/plan.md` + `.agent/ledger.md` + `git log/status`, reconciles any committed-but-unlogged slice, and resumes without re-dispatching completed tasks.

---

## 6. Triggered Post-L Environment Retro (Proposal-Only)
- **When to trigger**: Only after a bumpy L-level run (hit the 3-round breaker, repeated environment friction, or heavy navigation detours), right before cleaning `.agent/`. Skip for S/M and smooth L runs.
- **Inputs**: `.agent/ledger.md`, reworked `task-*-report.md`, and key error excerpts from `.agent/logs/` (audit **process & repo friction**, not the final code diff).
- **Check 3 areas**: (1) navigation gaps (`AGENTS.md` / `docs/ARCHITECTURE.md` pointers), (2) missing deterministic checks (`verify:fast` / lint / types), (3) recurring patterns to promote to mechanical rules or `docs/glossary.md`.
- **Proposal-only**: Output at most 3–5 prioritized proposals; prefer deterministic checks/pointers over adding prose warnings to `AGENTS.md`. Never edit `AGENTS.md`, CI, or guardrails without explicit human approval.
