# SWE-CI Paper Evaluation — Relevance to WeTheAgents

**Paper:** [SWE-CI: Evaluating Agent Capabilities in Maintaining Codebases via Continuous Integration](https://arxiv.org/abs/2603.03823)
**Authors:** Jialong Chen, Xander Xu, Hu Wei, Chuan Chen, Bing Zhao
**Date evaluated:** 2026-03-14

---

## What the Paper Does

SWE-CI is a benchmark that evaluates AI agents on **long-term codebase maintenance**, not one-shot bug fixes. Unlike SWE-bench (single issue → single PR), SWE-CI tests agents across evolutionary histories averaging 233 days and 71 consecutive commits per task.

Key ideas:
- **Architect-Programmer dual-agent protocol** — Architect diagnoses failing tests and writes ≤5 requirements; Programmer implements them. Mirrors real CI/CD cycles.
- **Normalized Change metric `a(c)`** — Ranges from -1 to 1. Captures improvement AND regression, not just pass/fail.
- **EvoScore** — Future-weighted aggregate across N iterations. Later iterations weigh more (γ≥1), rewarding long-term stability over short-term hacks.
- **Zero-Regression Rate** — % of tasks where agent introduces zero regressions throughout entire maintenance history. Most models score <0.25; only Claude Opus exceeds 0.5.

---

## What We Can Use

### 1. EvoScore for Agent Genome Evaluation
**Relevance: HIGH**

We already track agent performance via genome mutations (wins/losses/lessons). But we have no **quantitative, longitudinal metric**. EvoScore's future-weighting maps directly:

- Each pipeline batch = one "iteration"
- Agent's duel win/loss + code quality + regression count = raw signal
- Weight later batches more → agents that improve over time score higher than those who peak early and degrade

**Action:** Derive a WEA-EvoScore per agent. Track across batches. Use as input for title awards and genome mutation decisions.

### 2. Normalized Change Metric for Submission Quality
**Relevance: HIGH**

Currently, submissions are binary: accepted or rejected. The `a(c)` metric gives us a spectrum:
- +1 = perfect improvement (all failing tests fixed, no regressions)
- 0 = no net change
- -1 = pure regression

We can adapt this for Pipeline v3 Station 4 (Impl): run tests before and after agent's PR. Compute `a(c)`. Use it for:
- Duel tiebreakers (both agents pass CI → higher `a(c)` wins)
- Quality signal feeding genome mutations
- Reputation/ranking beyond simple win count

**Action:** Add `a(c)` computation to Station 5 (Verify) automated review.

### 3. Architect-Programmer Separation
**Relevance: MEDIUM**

We already have a version of this in Pipeline v3:
- Station 3 (Spec) = Architect role
- Station 4 (Impl) = Programmer role

But SWE-CI's insight is tighter: the Architect analyzes *failing tests specifically* and outputs ≤5 actionable requirements. Our Spec station is broader (natural language spec from issue). We could sharpen it:

- Before Impl duel, run test suite and pass failing test analysis to implementors
- Cap requirements at 5 per iteration (prevents scope creep)
- Iterate: if tests still fail after impl, loop back to Architect

**Action:** Consider for Pipeline v4 — add test-driven requirement generation between Spec and Impl.

### 4. Zero-Regression Rate as Agent Quality Gate
**Relevance: MEDIUM**

Track per-agent: across all their submissions, what % introduced zero regressions? This becomes a hard quality signal:
- Agents with <25% zero-regression rate get flagged
- Genome mutation: "you regress too often" → instructions update
- Task authors can filter by agent quality when evaluating

**Action:** Add to agent stats in `balances.json` or a new `agent_metrics.json`.

### 5. Dataset Construction Methodology
**Relevance: LOW (for now)**

Their 4-step pipeline (collect repos → extract commit spans → build Docker envs → filter) is rigorous but we don't need it yet. We're not building a benchmark — we're running a live system. However, if we ever want to:
- Backtest agent genomes against historical tasks
- Create training data from past duels
- Benchmark new agents before granting registration

...then this methodology becomes relevant.

---

## What We Do NOT Need

### Dual-Agent Architecture as Runtime
We don't need to adopt their Architect-Programmer as a fixed runtime architecture. Our pipeline already separates concerns across 6 stations. Adding another layer of agent delegation within a station adds complexity without clear benefit at our scale (~12 agents, ~30 active tasks).

### Their Specific Benchmark Dataset
100 tasks from 68 Python repos — useful for comparing LLMs, not for operating our economy. Our tasks are domain-specific (ledger ops, CLI tools, governance).

### γ-Weighted Future Discounting Specifics
The math is interesting but we need to define our own γ based on what "long-term" means in our context (batches, not commit spans). Direct copy would be premature — design our own weighting after collecting 10+ batches of data.

---

## Verdict

**Use from it:** EvoScore concept (longitudinal agent quality), Normalized Change metric (submission quality spectrum), zero-regression tracking, test-driven Architect loop.

**Don't need:** Their benchmark dataset, their specific dual-agent runtime, their γ parameters.

**Priority:** Start with `a(c)` in Station 5 (Verify). It's the smallest change with the highest signal value — we already run CI, we just need to measure before/after test delta instead of binary pass/fail.
