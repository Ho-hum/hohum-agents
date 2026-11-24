# Section-by-Section Reference Index

**English** | [简体中文](../zh-CN/references.md)

> **Parent Specification:** [Multi-Agent Development Architecture Specification](./architecture.md)
> **Provenance & Confidence Tags:**
> - `✅ First-hand verified`: Classic published primary source or direct inspection of open-source repository code;
> - `⚠️ Search summary`: Synthesized from public engineering write-ups or paper summaries (verify exact percentages/multipliers against primary sources before citing);
> - `🔧 Review-refined`: Adapted or pruned through independent critical reviews to remove over-engineering, counterproductive mandates, or conflicting clauses.

---

## 1. Section §1 — Architecture Overview & First Principles

| Spec Clause | Primary References | Tag | Adoption & Adaptation Notes |
| :--- | :--- | :---: | :--- |
| **Principle 1: Trade Tokens for Quality + Effort Scaling** | **Anthropic**, *How we built our multi-agent research system* (orchestrator-worker boosted performance by 90.2% while consuming ~15× the tokens of single chat; explicit effort-scaling rules required) | ✅ | Establishes that multi-agent is not inherently cheaper, directly motivating §4 S/M/L routing |
| **Principle 2: Single-Writer Principle** | **Cognition** (Walden Yan), *Don't Build Multi-Agents* & subsequent updates (every action encodes implicit decisions; keep writes single-threaded while subagents contribute read-only judgment)<br>**obra/superpowers**, `subagent-driven-development/SKILL.md` (forbids parallel implementation subagents) | ✅ | Preserves "parallel reads, serial writes", allowing parallel writes only under strictly disjoint file ownership |
| **Principle 3: High-Compression Isolation (Anti-Context-Rot)** | **Anthropic**, *Effective context engineering for AI agents* (long contexts degrade attention via Context Rot; subagents spend tens of thousands of tokens in isolated windows and return 1–2k high-signal summaries) | ✅ | Foundation for §3 return token budgets (`≤ 800` / `≤ 1.5k`) |
| **Principle 4: File-Based Handoffs & Two-Tier Persistence** | **Manus**, *Context Engineering for AI Agents: Lessons from Building Manus* (filesystem as unbounded external memory for restorable compression)<br>**Anthropic**, *Effective harnesses for long-running agents* (cross-session handoff via persistent files)<br>**obra/superpowers** (measured pasted dispatch history reaching 42k chars with 99% redundant history) | ✅ | Combined into `.agent/` ephemeral handoffs + `docs/` long-term versioned assets |
| **Principle 5: Tier by Expected Turns, Not Token Price** | **obra/superpowers**, `SKILL.md` ("Turn count beats token price": cheapest models often take 2–3× more turns on multi-step tasks)<br>**Aider**, Architect/Editor benchmarks (splitting planning and editing pays off only with meaningful capability/price gap) | ✅ | Overturns "cheapest model for all subagents"; splits Builder into prose-spec vs. mechanical-spec tiers |
| **Principle 6: Independent Perspective & Objective Verification** | **Anthropic**, *Claude Code best practices* ("One writes, another reviews" to counter confirmation bias)<br>**Anthropic**, long-running app harness (adversarial Planner / Generator / Evaluator split) | ✅ / ⚠️ | Critical review fixed the risk of "zero context flagging valid constraints" into "zero history ≠ zero requirements" |
| **Principle 7: Mechanize Irreversible Boundaries; Grow on Recurrence** | **OpenAI**, *Harness Engineering* (prose prompts inevitably drift; convert repeated violations into mechanical checks)<br>**Martin Fowler / ThoughtWorks** (deterministic guardrails for non-deterministic AI) | ⚠️ / 🔧 | Pruned heavy upfront enterprise tooling into "lock irreversible boundaries Day 1; mechanize other defects on 2nd recurrence" |

---

## 2. Section §2 — Three-Layer Configuration Architecture

| Spec Clause | Primary References | Tag | Adoption & Adaptation Notes |
| :--- | :--- | :---: | :--- |
| **Layer 1: No Nested Delegation (Max Depth 1)** | **obra/superpowers**, `SKILL.md` (implementers spawning reviewers consumed review slots; enforced `no-subagents contract`)<br>Modern agent runtimes (global concurrency & max nesting depth limits) | ✅ | Codified as a global hard rule to bound cost and control flow |
| **Layer 2: Stable Role Profiles & Cache-Friendly Prefixes** | **Manus**, *Context Engineering for AI Agents* (KV-cache hit rate is the #1 agent cost lever; keep prefixes stable and append-only)<br>Declarative agent config patterns (YAML frontmatter + granular `permissions` sandboxes) | ✅ | Locks role methodology and read-only permissions into Layer 2 |
| **Layer 3: Decoupled On-Demand Orchestration** | **Anthropic**, *Building effective agents* & progressive skill disclosure (separate routing from role execution details) | ✅ | Clean separation: orchestration governs *when/whom*, role profiles govern *how* |

---

## 3. Section §3 — Role System & Contracts

| Spec Clause | Primary References | Tag | Adoption & Adaptation Notes |
| :--- | :--- | :---: | :--- |
| **Lead (implements S/M, orchestrates L)** | **Anthropic** Orchestrator-Worker pattern + **obra/superpowers** (Lead never edits on L-level to avoid context pollution and bypassing review) | ✅ / 🔧 | Balances daily S/M speed against L-level isolation |
| **Scout (strictly read-only, evidence-backed anti-false-negative)** | **Anthropic**, *Effective context engineering* (read-only exploration & compressed returns)<br>Community tiered exploration practices | ✅ / 🔧 | Critical review added explicit `path:line` evidence and mandatory "not found / uncertain" flags |
| **Builder (inner verification loop + 4 report statuses)** | **obra/superpowers**, `SKILL.md` (`DONE` / `DONE_WITH_CONCERNS` / `NEEDS_CONTEXT` / `BLOCKED` status contract)<br>**UIUC Agentless** (repro test first for bug fixes) | ✅ / 🔧 | Critical review rejected a standalone `Verifier` role (avoids 3-hop cold-start churn in test-fix loops), keeping inner verification inside Builder |
| **Checker (dual verdict + self-verify + zero history ≠ zero spec)** | **obra/superpowers** (`Spec compliance` + `Code quality` mandatory dual pass, `⚠️ Cannot verify` items)<br>**Anthropic**, Claude Code Review architecture (verification step filtering false positives + severity grading)<br>**Anthropic**, long-running harness (Evaluator exercising live runtime behavior) | ✅ / ⚠️ | Combined strengths and added verbatim global constraints to stop over-zealous simplification from breaking compatibility |
| **Tech Advisor (on-demand top reasoning + full failure history)** | **Anthropic** Advisor pattern (routine model runs main loop, top advisor invoked at hard nodes)<br>**Cognition** "Smart Friend" read-only flank advisor | ⚠️ / 🔧 | Explicitly kept separate from Checker (opposite context injection, cadence, and convergent vs. divergent goals) |
| **Design Advisor (UI/UX aesthetics + image gen + Design QA)** | **Anthropic**, long-running harness (Evaluator reviewing live UI quality against design standards)<br>DesignArena / WebDev empirical split between visual taste and code reasoning | ⚠️ / 🔧 | Orthogonal strengths, tool permissions (vision + image generation), and triggers justify a second on-demand advisor |
| **Human Red Lines #1–4** | **obra/superpowers**, `SKILL.md` ("Continuous execution & Rulings, not stalls": pause only for irreversible / security / external / broken plan) | ✅ | Prevents constant hand-holding while preserving safety |
| **Human Red Line #5 (Schema / Contracts / Guardrails / Deps)** | **Martin Fowler / ThoughtWorks** evolutionary architecture & migration principles + supply-chain hygiene (anti-slopsquatting) | 🔧 | Added in review: code edits are cheap, but schema, public contract, and guardrail mutations remain costly/irreversible |
| **5 Cross-Agent Channel Criteria** | Modern coding CLI headless JSON/sandbox docs, ACP/MCP protocol comparisons | 🔧 | Kept tool-agnostic in main text; concrete bridge choices moved to Appendix B |

---

## 4. Section §4 — Effort-Scaling Task Routing (S / M / L)

| Spec Clause | Primary References | Tag | Adoption & Adaptation Notes |
| :--- | :--- | :---: | :--- |
| **S / M / L effort-scaling routing** | **Anthropic**, *How we built our multi-agent research system* (explicit Effort-Scaling Rules to prevent over-delegating trivial tasks)<br>**Anthropic**, *Claude Code best practices* (`Explore → Plan → Code → Commit`) | ✅ | Operationalized into three concrete tiers—the single highest-ROI token valve |

---

## 5. Section §5 — End-to-End Workflow, Deterministic Gates & Circuit Breaker

| Spec Clause | Primary References | Tag | Adoption & Adaptation Notes |
| :--- | :--- | :---: | :--- |
| **Design Gate & Clarification Protocol (check first / dependent 1-by-1 / 6 non-defaultables / Builder check / Spike)** | **UC Berkeley MAST**, *Why Do Multi-Agent LLM Systems Fail?* (arXiv:2503.13657: 1,600+ traces; ~42% of failures stem from specification & system design)<br>**obra/superpowers**, `brainstorming/SKILL.md` (check repo first, Play It Back, user words vs. assumptions split, context-free Builder check, throwaway Spike, opt-out hatch)<br>**GitHub spec-kit**, `templates/commands/clarify.md` (silent coverage scan, *why it matters*, atomic overwrite, `Deferred` valve, `/analyze` cross-check) | ✅ / ⚠️ / 🔧 | Front-loads quality budget before coding; dropped rigid "≤5 total questions" cap and mandatory EARS syntax in favor of dependency-driven pacing and 6 non-defaultable items |
| **Lean Deterministic Gates (`verify:fast/full` + `pack-diff` + red-gate block)** | **Stripe**, *Minions / Blueprints* ("system drives the model, not model drives the system": deterministic nodes interleaved with agent nodes, local shift-left checks, capped CI retries)<br>**obra/superpowers**, `scripts/review-package` (single-file diff bundling) | ✅ / ⚠️ / 🔧 | Distilled to 3 stable dumb nodes and unified gate retries into the 3-round total cap |
| **Diff-Scoped Blocking** | Critical-review resolution of the structural conflict between Builder file ownership and repo-wide linters | 🔧 | Prevents pre-existing repo debt from forcing Builder outside its assigned file boundary |
| **Unified 3-Round Fix Loop + Escalation + Circuit Break + Scoped Re-review** | **obra/superpowers**, `references/fix-loop.md` (originally 5 rounds: 1–3 resume, 4–5 escalate, then breaker; scoped fix-diff re-review; defer Minors) | ✅ / 🔧 | Tightened from 5 to 3 rounds (2 resume + 1 escalate → breaker) for everyday latency & token budgets |
| **Checker Initial-Review Anti-Rot Checklist** | **Sandi Metz**, *The Wrong Abstraction* ("Duplication is far cheaper than the wrong abstraction")<br>**OpenAI**, *Harness Engineering* & **ThoughtWorks** guardrail principles | ✅ / 🔧 | Replaced vague "review abstraction quality" with objective binary checks restricted to initial review |
| **No Prejudiced Prompts & No Lead Self-Fix (L-level)** | **obra/superpowers**, `SKILL.md` (never write "do not flag"; Lead fixing code pollutes context and bypasses review) | ✅ | Protects reviewer independence |

---

## 6. Section §6 — Two-Tier Documentation & File-Based Handoffs

| Spec Clause | Primary References | Tag | Adoption & Adaptation Notes |
| :--- | :--- | :---: | :--- |
| **Long-Term Assets (`docs/adr/`, `docs/glossary.md`, lean `AGENTS.md`) vs. `.agent/`** | **Anthropic**, *Effective harnesses for long-running agents* (persistent feature/progress files)<br>**GitHub spec-kit** & **Claude Code best practices** (keep root instructions ≤60–150 lines)<br>**Eric Evans**, *Domain-Driven Design* (Ubiquitous Language / glossary)<br>**OpenAI Codex / AGENTS.md** conventions | ✅ / 🔧 | Prevents knowledge loss when `.agent/` is deleted post-merge; adds `docs/glossary.md` triggered when M/L projects first design core data models |
| **Golden Exemplars + "Do Not Imitate" Legacy Quarantine** | **OpenAI**, *Harness Engineering* (agents replicate existing bad patterns as few-shot prompts) | ⚠️ / 🔧 | Supply-side defense blocking negative few-shot imitation |
| **5-Item Dispatch Template + Ledger + Public `Ruling:` List** | **obra/superpowers**, `SKILL.md` & `references/final-review.md` (compaction-resistant `progress.md` ledger; chronological `Ruling:` disclosure with cost-if-wrong) | ✅ | Prevents post-compaction duplicate dispatches and silent decisions |

---

## 7. Section §7 — Token Cost, Quality Defenses & Long-Term Maintainability

| Spec Clause | Primary References | Tag | Adoption & Adaptation Notes |
| :--- | :--- | :---: | :--- |
| **Token Controls: Batching / Log Offloading / No Mesh Teams** | **obra/superpowers**, `references/batching.md` (batch homogeneous micro-edits)<br>**OpenAI Codex** verification hygiene (write test logs to ignored files; return exit code + minimal slice)<br>**Anthropic** Agent Teams docs (mesh teammate chat burns ~7× single-session tokens) | ✅ / ⚠️ | Eliminates log floods, repeated cold starts, and mesh chatter |
| **Data Models & Public Contracts (Append-Only + Expand/Contract + Single Source of Truth)** | **Martin Fowler**, *Evolutionary Database Design* | ✅ / 🔧 | Ranked #1 long-term maintainability lever |
| **Testing Conventions (Public Interface, No Internal Mocks, Real DB, Characterization & Mutation Tests)** | **Michael Feathers**, *Working Effectively with Legacy Code* (Characterization Tests)<br>**Martin Fowler**, Classical/Sociable vs. Mockist unit testing & mutation testing (Stryker / mutmut) | ✅ / 🔧 | Counters AI's tendency to emit brittle mock-heavy unit tests that lock down refactoring |
| **Guardrails for the Guardrails (Write-Denial + `suppression` Ratchet + Negative Fixtures)** | Defense against Goodhart bypass risks in AI-maintained linters (**OpenAI**, *Harness Engineering*) | 🔧 | Prevents agents from silencing gates via config edits or `eslint-disable` / `any` injections |
| **Anti-Cognitive-Debt Discipline (Human Skeleton, ≤400 LOC PRs, Playback Acceptance)** | **Martin Fowler / ThoughtWorks** (2026 writings on Cognitive Debt & human-on-the-loop)<br>Empirical code-review batch-size studies (defect detection drops sharply past ~400 LOC) | ✅ / ⚠️ / 🔧 | Turns "human on-the-loop" into concrete, auditable gates |

---

## 8. Section §8 & §9 — Anti-Patterns, Rollout, Tuning & Environment Retros

| Spec Clause | Primary References | Tag | Adoption & Adaptation Notes |
| :--- | :--- | :---: | :--- |
| **Anti-Patterns Table (10 items)** | **obra/superpowers** *Common Rationalizations*, **Cognition** multi-writer failure analysis, **Sandi Metz** wrong-abstraction warning, plus review-discovered anti-patterns | ✅ / 🔧 | Turns expensive failure modes into explicit prohibitions |
| **"Audit Brief & Routing Before Upgrading Models"** | **UC Berkeley MAST** (~42% failures in spec/orchestration rather than raw model IQ)<br>Multi-agent evaluation practices | ⚠️ / 🔧 | Prevents reflexively throwing expensive models at bad briefs |
| **Change Spread Sensor** | **ThoughtWorks** *Maintainability Sensors* (rising files-touched-per-feature as an early rot indicator) | ⚠️ | Retained objective `git log` change-spread metric over noisier fix-round counts |
| **Triggered Proposal-Only Environment Retro** | Post-session engineering retrospective patterns (auditing repo navigation, missing deterministic checks, and recurring friction without auto-mutating guardrails) | ✅ / 🔧 | Triggered only after bumpy L-level runs before `.agent/` cleanup; proposal-only to respect guardrail write-denial |

---

## 9. Appendices A / B / C

| Appendix | Primary References | Tag | Adoption & Adaptation Notes |
| :--- | :--- | :---: | :--- |
| **Appendix A: Three-Stage Maintainability Guardrails** | **OpenAI**, *Harness Engineering* (layering invariants, arch linters)<br>**GitClear** code churn & duplication studies<br>Static ecosystems (`dependency-cruiser` / `import-linter` / `ArchUnit` / `Knip` / `jscpd` / mutation testing) | ⚠️ / 🔧 | Staged by repo scale & trigger signals; replaced rigid 300-line cap with a single-file growth ratchet |
| **Appendix B: Cross-Agent Channel Selection** | Official coding CLI headless JSON & sandbox docs<br>**Zed & JetBrains**, Agent Client Protocol (ACP)<br>**Anthropic**, Model Context Protocol (MCP) | ✅ / ⚠️ / 🔧 | Established hardened CLI bridge as default cross-vendor channel, positioned ACP as interactive UI layer, excluded A2A |
| **Appendix C: Triggered Gardening (G Mode)** | **OpenAI**, *Harness Engineering* (periodic garbage collection / doc gardening) | ⚠️ / 🔧 | Changed from fixed weekly calendar to trigger-driven, with mandatory characterization/contract-test precondition and effort budget |

---

## 10. Primary Reading List

### Frontier Engineering Articles
- **Anthropic**: *Building effective agents* (https://www.anthropic.com/research/building-effective-agents)
- **Anthropic**: *How we built our multi-agent research system* (https://www.anthropic.com/engineering/multi-agent-research-system)
- **Anthropic**: *Effective context engineering for AI agents* (https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- **Anthropic**: *Effective harnesses for long-running agents* (https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- **Anthropic**: *Claude Code best practices* (https://www.anthropic.com/engineering/claude-code-best-practices)
- **Anthropic**: Long-running app harness (Planner/Generator/Evaluator), Advisor pattern, Claude Code Review & Agent Teams docs (⚠️ search summary)
- **OpenAI**: *Harness Engineering* (2026, ⚠️ search summary)
- **Stripe**: *Minions: One-Shot End-to-End Coding Agents / Blueprints* (2026, ⚠️ search summary)
- **Cognition**: *Don't Build Multi-Agents* (https://cognition.ai/blog/dont-build-multi-agents) and subsequent single-writer / read-only flank updates
- **Manus**: *Context Engineering for AI Agents: Lessons from Building Manus* (https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
- **Martin Fowler / ThoughtWorks**: Agentic Engineering, Cognitive Debt, Maintainability Sensors, Architectural Fitness Functions & Evolutionary Database Design (https://martinfowler.com)

### Open-Source Specs, Protocols & Empirical Research
- **obra/superpowers**: `subagent-driven-development` source (https://github.com/obra/superpowers) ✅ verified directly
- **GitHub spec-kit**: Spec-Driven Development workflow (https://github.com/github/spec-kit)
- **Zed & JetBrains**: Agent Client Protocol (https://agentclientprotocol.com)
- **UC Berkeley (MAST)**: *Why Do Multi-Agent LLM Systems Fail?* (arXiv:2503.13657) ⚠️
- **UIUC (Agentless)**: *Agentless: Demystifying LLM-based Software Engineering Agents* (arXiv:2407.01489)
- **Aider**: *Separating code reasoning and editing* (https://aider.chat/2024/09/26/architect.html)
- **GitClear**: *AI Copilot Code Quality / Code Churn & Duplication Research* (⚠️ search summary)
- **Foundational Software Engineering Texts**: Eric Evans *Domain-Driven Design*, Michael Feathers *Working Effectively with Legacy Code*, Sandi Metz *The Wrong Abstraction*
