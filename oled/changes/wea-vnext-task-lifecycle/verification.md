# Verification: task lifecycle investigation

Date: 2026-09-07. Decision: source-boundary foundation accepted; detailed design and implementation are not ready.
Code under inspection: `22103c5`, based on canonical main `a741126`.

## Current behavior proof

Command:

```text
python -m pytest tests/vnext/test_current_bdd_plan_activation.py tests/vnext/test_current_bdd_plan_approval.py tests/vnext/test_current_bdd_flat_pod.py tests/vnext/test_current_bdd_authority.py tests/vnext/test_current_bdd_body_pause.py tests/vnext/test_resolution_plan_progression.py -q
```

Result: 31 passed in 2.30 seconds, exit 0.
This proves existing executor cases with synthetic evidence, not a GitHub task pipeline.

## Reproduced boundary mismatch

Used the existing current BDD helper to create a funded Flat PoD Plan and a normalized Work event.
Passed a valid public Markdown declaration through `parse_declaration`: accepted.
Constructed the corresponding `GitHubEvent` with the raw Markdown body and matching source identity, actor, and time.
Called the verified lifecycle path with that accepted evidence.
Result: `evidence_boundary: accepted GitHub revision content does not match`.
The original state hash remained unchanged. No network, Issue, or ledger write occurred.
The exploratory command completed with exit 0 after correcting its local test-package import path.

## Source anchors

- `src/wea_vnext/resolution_plan.py`: facade pins executor 0.8.0 and delegates verified lifecycle calls.
- `src/wea_vnext/executors/v0_8_0/declarations.py`: public Markdown grammar rejects protocol-computed fields.
- `src/wea_vnext/executors/v0_8_0/lifecycle.py`: LifecycleEvent normalizes a JSON source snapshot; the core requires exact GitHub body equality.
- `tests/vnext/current_bdd_support.py`: github_state constructs lifecycle source bodies from those normalized snapshots.
- `src/wea_vnext/executors/v0_8_0/intake.py`: verified activation requires author decisions, identity, funds, and accepted source evidence.
- `src/wea_vnext/executors/v0_8_0/lifecycle.py`: _settle and project_runtime derive payouts and escrow results.
- `src/wea_vnext/block9/github_native.py`: manifest targets contain the next event and financial indexes; financial replay consumes explicit postings.
- `oled/changes/wea-vnext-recreation/spec.md`: R-01, S-01C, public Work grammar, immutable source snapshots, and no general claim.
- `oled/changes/wea-vnext-block9-cutover/spec-1.1.md`: S-80 requires a retained real-task pilot.

The codebase-memory index was rebuilt for this worktree and used as a discovery lead.
Source inspection supplied the material conclusions; graph call counts do not prove dynamic-call absence.

BDD alignment gaps: raw-source integration for S-01C/S-03A/B; disk replay and task-derived settlement for S-71/S-80.
No changed runtime or new scenario is claimed implemented. Public/domain access and activation remain outside this investigation.

## Independent review and current authority

A fresh-context reviewer inspected the whole artifact against source and applicable instructions.
Result: no actionable findings. The reviewer confirmed the mismatch and the financial-posting boundary.
Source schema, bootstrap authority, and implementation proof remain explicit unfinished work.
The operator accepted Outcome 1.0 / Spec 1.0 and canonical-root pilot Issues during this investigation.
The proposed Agent0 payer and common-control pilot roles await the operator's answer.

The 2026-08-29 frozen input contains 19 v1 identity records and an empty conversion authority_bindings list.
Those v1 records contain usernames/operator labels; they do not directly instantiate the task runtime's versioned IdentityRegistry.
Do not treat this as proof that all historical authority evidence is absent or that genesis itself is invalid.
It is a bootstrap mapping/design gap before live task execution.
