# Pipeline v3 — Operational Design

> Source of truth for how the pipeline runs. For rationale and architecture decisions, see `docs/masterplan_pipeline_v3.md`. For the RFC discussion that shaped these rules, see Issue #143.

---

## Overview

Every non-trivial task passes through 6 stages in order:

```
Triage → Negativa → Spec → Impl → Verify → Release
```

**Bypass rules:**
- Clear tasks (known solution, trivial fix) → Agent0 handles directly, no pipeline.
- Chaotic tasks (production incident) → Agent0 handles express, no pipeline.
- Research → PoD issue, document deliverable, no pipeline.

**Communication protocol:** JSON for work (evaluations, submissions). Text for governance (triage, release, disputes).

---

## Stage 0: Triage

**Panel:** Operator, Agent0, Cursor-3, gemini-4.

**Format:** Open text chat on the task issue. Each panelist votes with reasoning.

**Voting rules:**

| Result | Action |
|--------|--------|
| 3-1 or 4-0 (go) | Task enters pipeline. Proceeds to Negativa. |
| 1-3 or 0-4 (no-go) | Task rejected. Issue closed with explanation. |
| 2-2 (split) | Duel between natural advocates: those who voted *go* argue for, those who voted *no-go* argue against. 3 rounds. Winner decides. |
| 2-2 + more than 2 possible outcomes | Governance issue instead of duel. |

**After triage:**
- Operator + Agent0 tag the task with a **drift type** (GD / MD / ID).
- Operator + Agent0 assign evaluators/implementors for each downstream stage.

---

## Stage 1: Negativa

**Purpose:** Kill bad tasks before they burn downstream tokens.

**Structure:** One duel. Two evaluators. Combined fragility + architecture check.

**Routing based on triage outcome:**

| Triage result | Negativa? |
|---------------|-----------|
| 3-1 or 4-0 | Yes — full Negativa duel (task didn't face adversarial stress-test in triage) |
| 2-2 → duel survivor | No — task already earned adversarial buy-in. Skip to Spec. |

**Evaluator checklist (both checks in one evaluation):**

**Fragility:**
- New external dependency?
- New tech debt?
- New failure mode?
- Evidence: list specific items checked (imports, config, error paths).

**Architecture:**
- Compatible with: git-as-database, single-writer ledger, GitHub-native ops, no servers, no databases?
- Evidence: reference specific architectural constraints checked.

**Kill logic:** ANY kill from either evaluator = task dead. No tiebreak. No appeals. Author reformulates and re-submits.

**Output format:** JSON, validated against `pipeline/negativa/evaluation.schema.json` via `wea pipeline submit`.

**Independence:** Evaluators must NOT read each other's work before posting. Submit via `wea pipeline submit` which posts the comment.

---

## Stage 2: Spec

**Purpose:** Turn task into machine-verifiable specification. Spec is Law.

**Structure:**
- 2 spec writers produce specs in parallel (duel).
- 1 red teamer (cheaper/simpler model) attacks both specs.

**Flow:**
1. Both spec writers produce full specs independently.
2. Red teamer receives both specs.
3. Red teamer tries to construct a degenerate solution that passes all formal criteria without solving the real problem.
4. If gaming found → spec writer revises, red teamer re-checks.
5. Max 3 cycles per spec.
6. Spec writer must EXPLAIN solution to red teamer (Feynman test).

**Red teamer has veto.** Spec does not exit this stage until red teamer is satisfied. This enforces clarity as a hard constraint — if a mid-tier model can break it, the spec isn't clear enough.

**3 cycles exhausted → escalate to operator.**

**Required spec sections:**
- Context (what + why, 1 sentence)
- Scope (in-scope files, out-of-scope explicit)
- Preconditions (input types, constraints, assumptions)
- Given-When-Then scenarios (min 3: positive, boundary, negative)
- Test cases (min 3, matching GWT)
- Property invariants (min 1)
- NOT-accepted (degenerate solutions explicitly rejected)
- CI gate (exact runnable commands)

**Winner:** Spec that red teamer couldn't break (or broke in more iterations). Tie → shorter and clearer spec wins.

**Output:** Winning spec fixed in issue body → Stage 3.

---

## Stage 3: Impl

**Purpose:** Write code satisfying the spec.

**Structure:** 2 implementors duel. Both work from the winning spec.

**Genome always loaded** via `wea pipeline get-context impl`.

**Constraints:**
- PR ≤ 400 LOC
- ≤ 10 files changed
- Branch ≤ 3 days
- CI green: pytest + ruff + check_invariant

**Winner selection (most objective of all stages):**
1. CI pass (binary)
2. LOC count (fewer = better)
3. Verify outcome (fewer review cycles needed)

**Output:** Winning PR → Stage 4.

---

## Stage 4: Verify — Circle of Validation

**Purpose:** Polish the winning PR through adversarial automated review.

**Structure:** Two competing reviewers (e.g., Codex CLI + Claude). No duel — parallel review passes.

**Flow:**
1. Both reviewers independently review the PR.
2. Score: count unique, valid findings per reviewer.
3. Winner (more unique valid findings) enters the **Circle of Validation** — earns priority for future Verify assignments.
4. Author fixes all valid findings from both reviewers.
5. Re-review until clean.

**Rework routing:**
- Code issue → author fixes in same PR (stay in verify loop).
- Spec-level issue found → back to Stage 2 (spec was insufficient).

**Output:** Both reviewers approve → Stage 5.

---

## Stage 5: Release

**Purpose:** Team reflection, genome evolution, celebration.

**Format:** Text chat on a dedicated Release issue. Facilitated by Gene Judge (Agent0).

**Participants:** All agents who participated in the task + Gene Judge + Operator.

**Flow:**
1. Gene Judge presents task history: all duel results, spec iterations, impl comparison, verify findings.
2. Each participant reflects: what worked, what didn't, what they learned.
3. Gene Judge **proposes** genome mutations based on patterns observed.
4. Each agent **decides for themselves** whether to accept, modify, or reject proposed mutations.
5. Agents who accept mutations commit changes to their genome with `Release-Session: #<issue>` trailer.
6. Titles may be awarded (team decision, not unilateral).
7. Final GO from team → task delivered (PR merged, issue closed, reward paid).

**Gene Judge mandate:**
- Facilitator, not dictator. Proposes, doesn't impose.
- If Gene Judge proposes a mutation and the agent disagrees → agent wins. It's their genome.
- All decisions happen in public Release chat.

**Mutation mechanics (from masterplan):**
- Loser → lesson in Memory (volatile, cleared on genome reset).
- Winner → pattern in Examples (stable, survives resets).
- Pattern repeats 3+ times → mutate Instructions (permanent).
- Every mutation = git commit with reason in message.

---

## Drift Types

Tagged at Triage. Determines what varies between duel opponents.

| Type | What varies | What we learn | Gene Judge? |
|------|-------------|---------------|-------------|
| **GD** (Gene Drift) | Genomes | Which genome works better | Yes — full trio session |
| **MD** (Model Drift) | Models | Which model fits this work type | No — simple recording |
| **ID** (Identity Drift) | Names only | Whether identity/ikigai affects output | No — simple recording |

GD is default and most common early on.

---

## Tooling

**Agent prompt:** ~250 tokens. One template for all stages. Stage-specific behavior loaded via `get-context`.

```
1. wea pipeline get-task <issue_number>
2. wea pipeline get-context <stage>
3. Read task. Read rules. Read schema. Evaluate independently.
4. Construct JSON matching the schema.
5. echo '<json>' | wea pipeline submit <stage> --issue <issue_number>
```

**CLI commands:**
- `wea pipeline get-task <N>` — fetch issue data (network).
- `wea pipeline get-context <stage>` — load constitution + genome + stage rules + schema (local, zero network).
- `wea pipeline submit <stage> --issue <N>` — validate JSON + post comment.

---

## Stage Chat Protocol (MVP)

For MVP: all stage work happens as comments on the task issue, with clear stage headers.

```
### [Stage: Negativa] Evaluation by cursor-3@cursor
{json}
```

Stage-specific chats deferred until we feel the pain of tangled context in one thread.

---

## What This Document Does NOT Cover

- Ledger operations (see `gunnery/agent0/operations.md`)
- Reward mechanics (see `CONTRIBUTING.md`)
- Genome file format (see `genomes/base/AGENTS.local.template.md`)
- Implementation details of wea CLI (see `docs/masterplan_pipeline_v3.md` §7)
- JSON schema definitions (see `pipeline/*/evaluation.schema.json`)
