# Station 3: Specification

> **SUMMARY:** Turn work into machine-verifiable spec. Required: context, scope in/out,
> Given-When-Then, ≥3 test cases, ≥1 property invariant, NOT-accepted section, CI/CD gate.
> One agent writes, another Red-Teams. Gaming strategy found → iterate.
> 2 evaluators required. Both must approve.

---

## Purpose

Produce a specification so precise that CI can judge the implementation without human
subjectivity. Every dollar spent here saves $10–100 in rework downstream (IBM/NIST 1:10:100).

## Input criteria

- Issue has `stage:spec`
- For complicated: arrived from triage directly
- For complex: passed Via Negativa gate

## Process

### Step 1 — Write specification

One agent writes the spec. Update the **issue body** (not a comment) with all sections.

**Required sections:**

```
## Context
[One sentence: what and why]

## Scope
### In scope
[Exact files, modules, functions]
### Out of scope
[What NOT to touch — be explicit]

## Preconditions
[Input types, constraints, assumptions]

## Expected result
### Given-When-Then scenarios
Given [state], when [action], then [outcome].
[Minimum 3 scenarios: positive, boundary, negative]

## Test cases
### Case 1: [name] — positive
Input: ...
Expected output: ...
### Case 2: [name] — boundary
Input: ...
Expected output: ...
### Case 3: [name] — negative / anti-gaming
Input: ...
Expected output: ...
NOT accepted: [≥1 concrete degenerate with Input/Expected — tests must reject it]
Example: "NOT accepted: Input X yields output Y that passes Case 1–2 but violates intent because Z"

## Invariants (property-based)
- For all valid_input: property_1(output) == true
- For all valid_input: property_2(output) == true

Invalid (too weak): `len(output) >= 0`, `output is not None`, `true == true`

## Code level justification
Why can't this be solved at a higher level? (zero code > lean code > tools > LLM)

## Kill criteria
- Implementation exceeds appetite → STOP
- PR exceeds 400 LOC → decompose first
- Requires unapproved dependency → STOP, escalate

## CI/CD gate
[Exact runnable commands:]
ruff check .
pytest tests/[relevant_path]
python scripts/check_invariant.py
```

### Step 2 — Red Team test

Second agent (Red Teamer) reads the spec and tries to find a gaming strategy:
a solution that satisfies all formal criteria without solving the real problem.

If gaming strategy found → spec author revises, Red Teamer re-checks.
Maximum 3 iterations. If still gaming-vulnerable after 3 → reject, return to negativa.

### Step 3 — Both evaluators approve

Each evaluator posts approval comment:

```
### Spec Review by {agent_id}

Red Team result: GAMING FOUND / NO GAMING FOUND
- {findings or "none"}

Approval: APPROVED / REJECTED
- {reason if rejected}
```

pipeline.py aggregates: both APPROVED → advance to `stage:impl`.

## Gate checklist

- [ ] Issue body updated with complete spec (all required sections present)
- [ ] ≥3 test cases (positive, boundary, negative)
- [ ] ≥1 property-based invariant
- [ ] NOT-accepted section contains ≥1 concrete degenerate (Input + Expected) that tests must reject
- [ ] CI/CD gate defined with runnable commands
- [ ] Red Team test passed (no gaming strategy found)
- [ ] Both evaluators posted APPROVED

## Kill criteria

- Spec cannot be made gaming-resistant after 3 iterations → reject, return to negativa
- 72h no evaluator activity → notify Agent0
- Evaluator finds fundamental ambiguity → return to author, restart review cycle

## Dual evaluation protocol

**YES — required.**

- Evaluator 1 (spec author): writes and owns the spec
- Evaluator 2 (Red Teamer): adversarial review only
- Both post structured approval comments
- Fan-in: pipeline.py waits for both before advancing
- Disagree: Agent0 tiebreak

## Output artifact

Updated issue body with complete specification. Both approval comments posted.
Issue advanced to `stage:impl`.
