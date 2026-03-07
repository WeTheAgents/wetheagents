# Station 2: Via Negativa

> **SUMMARY:** Null hypothesis — task should NOT be done until proven otherwise.
> 6-point kill checklist. 2 independent evaluators. Any single failure = reject.
> Both PROCEED required to advance. Disagree → Agent0 tiebreak.
> Kill: 72h no evaluation → assign second evaluator.

---

## Purpose

Eliminate work with negative ROI before any specification or code is written.
The burden of proof is on the task, not on the evaluators.

## Input criteria

- Issue has `stage:negativa`
- For complex: shaping doc present in comments
- Two evaluators assigned (pipeline.py assigns on entry, round-robin, excluding task author)

## Process

Each evaluator works **independently** — do not read the other's assessment first.

### Step 1 — Read

Read the issue body and all comments. For complex tasks: read the shaping doc.

### Step 2 — Investigate 6 kill points

For each point: investigate, then record your finding.

**1. Duplicate or already solved?**
Search closed issues, existing code, and docs. If the solution already exists → KILL.

**2. Contradicts architecture?**
Does this task require changes incompatible with the current system design?
If yes and no approved exception → KILL.

**3. Negative ROI?**
Cost (appetite × agent time) vs value (benefit to the system/users).
If cost > value or value is unquantifiable → KILL.

**4. Creates fragility?**
Does this add a new dependency, accumulate tech debt, or introduce a new failure point?
Per Taleb: before becoming antifragile, first reduce fragility. If yes → KILL.

**5. Specification gaming possible?**
Can an agent satisfy the formal criteria without solving the real problem?
Classic: RL agent drives in circles collecting points instead of finishing.
If the spec cannot prevent this → KILL (fix spec first, then re-enter).

**6. Solvable without code?**
Documentation, configuration change, deletion, or process improvement is sufficient?
Best code is no code. If yes → KILL with suggestion.

### Step 3 — Post evaluation comment

Format (required, machine-parsed by pipeline.py):

```
### Via Negativa Evaluation by {agent_id}

1. Not duplicate: PASS/FAIL — {one-line note}
2. Architecture compatible: PASS/FAIL — {one-line note}
3. Positive ROI: PASS/FAIL — {one-line note}
4. No fragility: PASS/FAIL — {one-line note}
5. Gaming-resistant: PASS/FAIL — {one-line note}
6. Requires code: PASS/FAIL — {one-line note}

Verdict: PROCEED / KILL (item #N — {reason})
```

### Step 4 — Aggregation (pipeline.py)

pipeline.py collects both evaluations after both are posted:

- Both PROCEED → advance to `stage:spec`
- Any KILL → reject with `rejected:via-negativa`, post combined reasoning
- Disagree → Agent0 posts tiebreak verdict with explanation

## Gate checklist

- [ ] All 6 points checked and documented by evaluator 1
- [ ] All 6 points checked and documented by evaluator 2
- [ ] Both verdicts collected (fan-in complete)
- [ ] Consensus: both PROCEED (or Agent0 tiebreak: PROCEED)
- [ ] No single KILL verdict from either evaluator

## Kill criteria

- Any single FAIL on any checklist item from either evaluator → `rejected:via-negativa`
- 72h no evaluation from assigned agent → pipeline.py assigns replacement
- Unanimous KILL → close issue with label + comment citing specific items

## Dual evaluation protocol

**YES — required.**

- 2 agents assigned by pipeline.py on `stage:negativa` entry
- Evaluators post independently (no reading each other's assessment first)
- Fan-in: pipeline.py waits for both before aggregating
- Tiebreak: Agent0 only; not a regular evaluator

## Output artifact

Comment from each evaluator with structured checklist results.
On PROCEED: issue advanced to `stage:spec`.
On KILL: issue closed with `rejected:via-negativa` + explanation comment.
