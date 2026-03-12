# Verify Stage

Purpose: prove the implementation is real, not just passing.

Protocol:
- Start with two reviewers.
- Compare unique valid findings.
- The stronger reviewer enters the Circle of Validation.

## Rubric Scoring Protocol

Each reviewer scores 10 rubrics on a 0.0–1.0 scale (higher = cleaner):

| Rubric | Weight | Description |
|---|---|---|
| `gaming` | 0.15 | Implementation passes tests but does not solve the real problem |
| `spec_conformance` | 0.15 | Implementation does not satisfy the GWT scenarios in the spec |
| `scope_violation` | 0.12 | Changes are made outside the declared scope of the task |
| `fragility` | 0.12 | Brittle patterns or assumptions that will break under normal change |
| `test_coverage` | 0.12 | New code paths lack test coverage |
| `dead_code` | 0.08 | Unused imports, commented-out blocks, or unreachable code paths |
| `error_handling` | 0.08 | Failure modes are not handled |
| `documentation` | 0.08 | Non-obvious design decisions are not documented |
| `performance_risk` | 0.05 | Algorithm complexity is unbounded or blocking calls in async context |
| `naming_clarity` | 0.05 | Names are non-self-documenting or misleading |

Score scale: `0.0` = problem definitely present, `1.0` = no problem found, `0.5` = minor/uncertain concern.

## Verdict Thresholds

The aggregator averages `overall_score` across all reviewers (recomputed from rubrics — submitted `overall_score` is stored for reference only):

- `avg >= 0.85` → **APPROVED**
- `0.60 <= avg < 0.85` → **HUMAN_REVIEW**
- `avg < 0.60` → **CHANGES_REQUESTED**

Rules:
- Verify does not reopen triage by default.
- If the spec itself is broken, route back explicitly and log why.

Output:
- structured reviewer findings (rubric scores + notes),
- `overall_score` float (aggregator recomputes from rubrics),
- verdict: `APPROVED`, `HUMAN_REVIEW`, or `CHANGES_REQUESTED`,
- rework route if needed.

## Refinement Loop

Two loops exist at Verify. Only the external loop creates GitHub artifacts.

### Internal loop (no protocol)

Implementor self-polishes before submitting the PR: codex review, fix, roast, fix.
No GitHub comments. No iteration tracking. Ends when the implementor is satisfied.

### External loop (structured protocol)

Triggered when a verify reviewer posts CHANGES_REQUESTED.

Steps:

1. **request-refinement**: run `wea pipeline request-refinement --issue <N>`. Reads the latest
   CHANGES_REQUESTED evaluation, validates and posts a refinement_request JSON comment
   listing exact blocking_comments. Fails if a request for that iteration already exists.

2. **Fix**: implementor addresses every item in blocking_comments, updates the PR.

3. **Re-review**: reviewer posts a new verify evaluation with `"iteration": <previous + 1>`.
   The reviewer increments the counter. The CLI does not.

4. **Loop or close**: APPROVED = done. CHANGES_REQUESTED and iteration < verify_max_iterations:
   repeat from step 1.

5. **ESCALATE**: CHANGES_REQUESTED and current_iteration >= verify_max_iterations (default 3).
   `wea pipeline refinement-status --issue <N>` reports ESCALATE. Human judgment required.
   No automated action is taken. Exit code is 0.

Check state at any time: `wea pipeline refinement-status --issue <N>`
