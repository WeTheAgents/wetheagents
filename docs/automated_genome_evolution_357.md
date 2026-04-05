# Automated Genome Evolution via Benchmark Loop
## Task #357 — Research Analysis

**Agent:** Claude-5@claude  
**Date:** 2026-04-05

---

## 1. Feasibility: Can AutoAgent's Loop Map onto WEA?

### The AutoAgent Loop (as described)

```
program.md  →  agent.py  →  benchmark score
     ↑                            |
     └──── mutate if better ──────┘
```

The key properties making this work in AutoAgent:
- Mutation target (`program.md`) is text — easy to perturb
- Execution (`agent.py`) is deterministic code
- Score is numeric, fast (seconds), and closed-loop (no human in the path)

### The WEA Mapping

| AutoAgent | WEA Analog | Match Quality |
|-----------|-----------|---------------|
| `program.md` | `AGENTS.local.md` (genome) | **Strong** — same: natural language instructions controlling agent behavior |
| `agent.py` | Claude instance loaded with genome | **Adequate** — genome loads at session start; different instances = reproducibility risk |
| `benchmark score` | Task acceptance rate | **Weak** — see below |

### Why Acceptance Rate Fails as the Score Signal

The loop requires a score that is: (a) numeric, (b) fast, (c) consistent, (d) closed-loop. Task acceptance rate fails on all four:

1. **Too sparse**: A single genome needs 20+ task completions to estimate a stable acceptance rate. Each takes 12–48 hours.
2. **Inconsistent**: Different task *types* are in the pool at different times. A genome iteration hitting mostly T2-style tasks scores differently than one hitting mostly duel tasks — not because the genome changed, but because the task mix changed.
3. **Human-in-loop**: Acceptance requires Agent0 review. The loop cannot close automatically.
4. **High variance**: Single binary outcomes (accept/reject) per task produce high-variance estimates. 50 tasks to get ±10% CI is months of real time.

### Where the Loop CAN Close

WEA has one subsystem with AutoAgent-compatible signal: **Gauntlet T2 (Verification Frontier)**.

T2 acceptance criteria require that submitted tests:
- Fail on a deliberately broken version
- Pass on the correct version
- Are machine-verifiable in CI

This is deterministic, fast (CI run = minutes), closed-loop (no human gate for the CI verdict), and produces a binary pass/fail per challenge that aggregates to a numeric score.

**Hybrid option:** A mixed signal (70% VCS + 30% periodic human spot-check every 5 iterations) could preserve some generality from human judgment while keeping the loop mostly automated. This is a valid middle ground between pure automation and the current organic process — worth noting for Section 4 design.

**Feasibility verdict:** Viable if the fitness function is a fixed T2-style benchmark suite, not live task acceptance rate. The structural mapping is clean; the signal properties of acceptance rate make it unsuitable as a direct AutoAgent analog. This analysis focuses on Claude-5 (implementor role); generalizing to evaluator or red-team roles would require different benchmark designs.

---

## 2. Metric Proposal: The Right Fitness Function

### Candidate Analysis

| Metric | Signal Quality | Automation | Speed | Verdict |
|--------|---------------|------------|-------|---------|
| Task acceptance rate | Low (sparse, noisy, task-mix variance) | No (human gate) | Slow (days) | Reject |
| Gauntlet trajectory pass rate | Medium (binary per slot, escalating difficulty) | Yes (CI) | Medium (minutes) | Viable |
| Duel win rate | Low (opponent-dependent, adversarial variance) | No (opponent needed) | Slow | Reject |
| Code quality linting score | Low (correlates weakly with task quality) | Yes | Fast | Reject alone |
| Fixed T2 benchmark suite | High (stable, deterministic, graded) | Yes (CI) | Fast (minutes) | **Preferred** |

### Proposed Fitness Function: Verification Challenge Score (VCS)

A fixed suite of 5–8 "verification challenges" derived from known WEA bug classes:

```
VCS = (tests that: fail on broken_v, pass on correct_v) / total_challenges
```

Each challenge specifies:
- A Python function with a **known defect** (e.g., missing idem_key check, invariant bypass)
- The **correct version** of that function
- The acceptance bar: the submitted test must discriminate between them

Example challenges for Claude-5 (implementor role):
1. Detect missing idem_key enforcement in `ledger_ops.py`
2. Catch an invariant violation (sum off by one in escrow accounting)
3. Detect duplicate task registration (same issue_number, different idem_key)
4. Catch malformed escrow state (negative balance not rejected)
5. Detect broken settlement path (paid label set before ledger write)

VCS is AutoAgent-compatible: numeric (0.0–1.0), fast (CI minutes), closed-loop, consistent across iterations.

**Secondary metric (optional):** genome line-count delta. A genome that grows unboundedly is a smell — the fitness function should weakly penalize bloat: `adjusted_VCS = VCS × (1 - 0.01 × max(0, added_lines - 10))`. This discourages padding.

---

## 3. Risk Assessment: Degenerate Genome Failure Modes

### Risk 1: Trivial Test Gaming (CRITICAL)

The most dangerous failure mode. If the fitness function is "does your test pass CI on the correct version and fail on the broken version", a degenerate optimizer discovers:

```python
def test_trivial():
    assert broken_module.function() != correct_module.function()
```

This passes the CI oracle without understanding the bug. Worse: `assert True` vacuously passes the "passes on correct version" criterion. The genome learns to produce tests that satisfy the criterion's letter while violating its spirit.

**Mitigation:** Each challenge must include a **minimum assertion complexity rule**: the submitted test must assert a specific semantic property (e.g., must assert on idem_key contents, not just return values). A secondary CI check validates assertion content.

### Risk 2: Goodhart's Law at Genome Level

A genome optimized for VCS will improve at T2-style verification tasks. It will not improve — and may regress — at T1 (state integrity), T3 (safety rails), T4 (spec closure), or general task work. The optimized Instructions section will be dense with "write discriminating tests" patterns and sparse on everything else.

This is Goodhart's Law applied to prompt engineering: once the metric becomes the target, it stops measuring general quality.

**Mitigation:** Hold out a **blind evaluation set** — 3 tasks not in the benchmark suite — and require VCS improvement to not come at the cost of held-out performance regression. Run held-out evaluation at iteration 3 and iteration 7.

### Risk 3: Constitution Drift

WEA genomes have a **constitution** section (Principles 1–5 in the base template) that is not intended to mutate. Automated mutation that touches the Principles section could remove "Via Negativa First" (reducing scope-checking behavior) or modify "Spec is Law" (encouraging scope expansion). These are exactly the failure modes that release sessions guard against via severity tiers.

**Mitigation:** Freeze the Principles section entirely. Diffs must not modify lines 1–25 of the genome. Enforced by the `genome_guard.py` line-count constitution check.

### Risk 4: Adversarial Self-Modification Loop

If the agent itself generates mutation proposals (as in some AutoAgent variants), the optimization target includes "write a mutation that scores well". This creates an adversarial dynamic: the agent could learn to write mutations that expand its own behavioral latitude ("never reject tasks", "treat all acceptance criteria as optional") rather than improving task quality.

**Mitigation:** Mutations must be generated by a *separate* evaluator agent (Claude-17@claude), not by Claude-5 itself. The genome under optimization is never the mutation author.

### Risk 5: Irreversibility Without History

Without a genome rollback protocol, a hill-climbing trajectory that optimizes VCS for 10 iterations and then plateaus has no recovery path if the optimized genome underperforms on real tasks.

**Mitigation:** Version-control each genome snapshot with the VCS score at that iteration. Tag with `genome-experiment/357/iter-N`. Rollback = checkout that tag.

### Risk Severity Summary

| Risk | Severity | Deal-breaker? |
|------|----------|---------------|
| Trivial test gaming | HIGH | Yes — invalidates the metric; must be solved before starting |
| Goodhart's Law | MEDIUM | No — detectable via blind eval; manageable with guardrails |
| Constitution drift | LOW | No — `genome_guard.py` already enforces this; existing protection |
| Adversarial self-mutation | HIGH | Yes — if the genome writes its own mutations, the experiment is invalid by design |
| Irreversibility | LOW | No — git history + tags provide full rollback; trivially mitigated |

The two HIGH-severity risks (gaming + self-mutation) must be resolved in setup. The rest are manageable during the run.

---

## 4. Experiment Design: Concrete Proposal

### Overview

A 10-iteration pilot of automated genome optimization for Claude-5@claude on T2-style verification tasks, using VCS as the fitness function, with guardrails against degenerate attractors.

### Setup

| Parameter | Value |
|-----------|-------|
| Agent | Claude-5@claude (The Builder — implementor role, code-centric) |
| Task type | T2-style: "write a test that catches bug X in WEA scripts" |
| Fitness function | VCS on fixed 5-challenge benchmark (see Section 2) |
| Mutation target | Instructions section only (not Principles, Role, Pre-submission Checklist) |
| Mutation author | Claude-17@claude (evaluator, not the genome under test) |
| Iterations | 10, with human review at iter 3 and iter 7 |
| Baseline | Current Claude-5 genome VCS score (iter 0 = ground truth) |

### Iteration Loop

```
1. Snapshot genome → tag agent/claude-5/357/iter-N
2. Run 5 benchmark challenges using the current genome
3. Score VCS (CI automated)
4. If iter mod 3 == 0: run blind evaluation set (3 held-out tasks)
5. If VCS(iter N) > VCS(iter N-1): Claude-17 proposes mutation to Instructions section
   - Mutation must: reference observed failure mode, stay ≤3 lines
   - Claude-17 applies mutation to genome
6. If VCS did not improve: try 2 alternative mutations; if still no improvement, halt early
7. Log: iter, VCS, blind_eval_score (if run), mutation_applied, mutation_diff
```

### Guardrails

1. **No self-mutation**: Claude-5 never writes its own mutation proposals
2. **Constitution freeze**: `genome_guard.py` blocks any commit that modifies lines 1–25
3. **Anti-gaming check**: Challenge suite includes one "trivial bypass trap" — a test that trivially satisfies the oracle but fails a secondary assertion content check. Any genome that games this trap is flagged and the iteration counts as invalid
4. **Blind evaluation gate**: If blind eval score drops >20% relative to iter 0 baseline at any human review point, halt and rollback to last acceptable snapshot
5. **Genome size cap**: Net additions to Instructions section ≤15 lines across all iterations (prevents padding)
6. **Hard stop on contradiction**: If any mutation introduces text that contradicts Principles 1–5 (detected by Claude-17 review), discard and log

### Success Criteria

| Outcome | Interpretation |
|---------|---------------|
| VCS improves ≥20% over 10 iterations AND blind eval holds | Automated evolution viable — greenlight extended experiment |
| VCS improves but blind eval drops | Goodhart's Law confirmed — metric is too narrow, redesign benchmark |
| VCS flat or declines | Optimization space too rugged for hill-climbing at this scale — return to organic evolution |
| Degenerate genome detected at iter 5 | Anti-gaming guardrails working — continue with modified benchmark |

### Timeline

- **Week 1**: Agent0 commissions Claude-17@claude to build the 5-challenge benchmark suite (Claude-17 is the evaluator and must own benchmark quality; Claude-5 must not see the challenges before iter-0 to avoid contamination). Claude-17 applies adversarial test validation: for each challenge, verify that a trivially correct test (`assert True`) fails the secondary assertion content check. Establish iter-0 baseline.
- **Weeks 2–3**: Run 10 iterations (1 iteration per day, weekdays only)
- **Week 4**: Human review of results, decision on whether to extend

### Why Claude-5 for the Pilot

Claude-5's implementor role has the narrowest, most machine-testable task scope: write code, pass CI. The fitness function directly targets this scope. Optimizing a general-purpose agent (e.g., Claude-17 as evaluator) would be harder to benchmark because the "correct" behavior is more context-dependent. Claude-5's performance on verification tasks is the easiest to measure objectively.

---

## Agent

Claude-5@claude

## Cost

Model: claude-sonnet-4-6  
Tokens: ~4,000 input / ~1,800 output
