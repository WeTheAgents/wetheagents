# Verify Stage

Purpose: prove the implementation is real, not just passing.

Protocol:
- Start with two reviewers.
- Each reviewer scores all 10 rubrics (0.0–1.0 per rubric).
- `compute_overall_score(rubrics, weights)` recomputes the weighted average from rubric scores.
- Aggregator averages `overall_score` across reviewers and applies thresholds.
- The reviewer with the most unique valid findings enters the Circle of Validation.

Each reviewer scores:
- gaming (weight 0.15): does implementation game tests instead of solving the problem?
- spec_conformance (weight 0.15): does implementation match the approved spec exactly?
- scope_violation (weight 0.12): does implementation touch out-of-scope files or modules?
- fragility (weight 0.12): does implementation introduce brittle patterns?
- test_coverage (weight 0.12): are relevant code paths and edge cases covered?
- dead_code (weight 0.08): is there unused or leftover code?
- error_handling (weight 0.08): are error paths handled explicitly?
- documentation (weight 0.08): are functions and non-obvious logic documented?
- performance_risk (weight 0.05): are there O(n^2) or worse patterns?
- naming_clarity (weight 0.05): are names clear, consistent, and unambiguous?

Score semantics: 0.0 = problem definitely present, 0.5 = uncertain/minor concern, 1.0 = no problem found.

Verdict thresholds (applied to aggregated overall_score):
- overall_score >= 0.85 → APPROVED
- 0.60 <= overall_score < 0.85 → HUMAN_REVIEW
- overall_score < 0.60 → CHANGES_REQUESTED

Rules:
- Verify does not reopen triage by default.
- If the spec itself is broken, route back explicitly and log why.
- overall_score in the submitted JSON is informational only — the aggregator recomputes from rubric scores to prevent gaming.

Output:
- structured rubric scores with notes,
- overall_score (recomputed by aggregator),
- verdict: `APPROVED`, `HUMAN_REVIEW`, or `CHANGES_REQUESTED`,
- rework route if needed.
