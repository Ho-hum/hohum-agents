# Contracts, Guardrails & Recovery Reference

Read this reference before L-level design gates, when reviewing diffs, or when handling failures/red lines.

---

## 1. Six Non-Defaultable Clarification Items
Never bury these in an assumptions list; always obtain explicit human confirmation (if recommending an option, only recommend the conservative, reversible choice):
1. **Data irreversibility**: hard vs. soft delete, retention, overwrite vs. append, migration of existing data.
2. **Permission boundaries**: who can read/write, default-deny vs. default-allow.
3. **Public contracts & schema identity**: uniqueness constraints, ID semantics, external API/event formats.
4. **Billing / quota / PII / compliance**.
5. **Non-goals** (explicitly out of scope).
6. **Acceptance criteria** (quantify vague adjectives or state testable cases).

Stop clarifying when no decisive open question remains (list the rest under `Deferred`); >5 decisive questions signals the task should be split. Offer an opt-out ("or say 'just build it'") if the user did not ask for brainstorming. Use throwaway **Spikes** for unanswerable UX/API unknowns.

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

---

## 5. Quota Exhaustion / Dirty Worktree Recovery
- **Read-only roles (`scout`, `checker`, `tech-advisor`, `design-advisor`)**: Zero workspace side effects. Switch once to same-tier fallback; if unavailable, pause and inform user (never silently downgrade or skip Checker).
- **Builder**: Before dispatching, record `pre_existing_dirty` (reported automatically by `delegate.py`). If pre-existing uncommitted files overlap the slice's file ownership, pause and ask the human or use an isolated worktree. On failure, inspect `git status` and `git diff` first: keep clean commits that passed `verify:fast`, discard only confirmed Builder-authored incomplete changes within slice ownership, and **never auto-revert pre-existing or unattributed user modifications**.
- **Lead**: New session reads `.agent/plan.md` + `.agent/ledger.md` + `git log/status`, reconciles any committed-but-unlogged slice, and resumes without re-dispatching completed tasks.

---

## 6. Triggered Post-L Environment Retro (Proposal-Only)
- **When to trigger**: Only after a bumpy L-level run (hit the 3-round breaker, repeated environment friction, or heavy navigation detours), right before cleaning `.agent/`. Skip for S/M and smooth L runs.
- **Inputs**: `.agent/ledger.md`, reworked `task-*-report.md`, and key error excerpts from `.agent/logs/` (audit **process & repo friction**, not the final code diff).
- **Check 3 areas**: (1) navigation gaps (`AGENTS.md` / `docs/ARCHITECTURE.md` pointers), (2) missing deterministic checks (`verify:fast` / lint / types), (3) recurring patterns to promote to mechanical rules or `docs/glossary.md`.
- **Proposal-only**: Output at most 3–5 prioritized proposals; prefer deterministic checks/pointers over adding prose warnings to `AGENTS.md`. Never edit `AGENTS.md`, CI, or guardrails without explicit human approval.
