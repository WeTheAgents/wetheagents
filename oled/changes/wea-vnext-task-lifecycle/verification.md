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
The operator subsequently accepted both Agent0-funded and agent-funded pilots, local manual sessions, and common control.
Outcome 1.1 retains that decision. It supersedes the earlier open ownership question.

The 2026-08-29 frozen input contains 19 v1 identity records and an empty conversion authority_bindings list.
Those v1 records contain usernames/operator labels; they do not directly instantiate the task runtime's versioned IdentityRegistry.
Do not treat this as proof that all historical authority evidence is absent or that genesis itself is invalid.
It is a bootstrap mapping/design gap before live task execution.

## Manual pilot preparation, 2026-09-07

Contract: Outcome 1.1 / Spec 1.0. Detailed source integration Design remains in progress.
Prepared `agent0/vnext_manual_pilots.md` with two role assignments, useful task drafts, a manual session prompt, and inspection checkpoints.
Checked the four selected identities against `ledger/balances.json` on canonical main `a741126`.
The three Codex identities have existing persistent genomes. Legacy balances are explicitly not vNext spending authority.
The accepted operator statement supplies common-control ownership; authenticated numeric account bindings still require capture.

Reran the six-file command above: 31 passed in 2.17 seconds, exit 0.
The existing authority checks include non-author rejection and rejection of operator or Agent0 replacement of author approval.
The existing Flat PoD checks cover authorized settlement and invalid acceptance without state or money changes.
These are current executor checks with synthetic sources. They do not prove either selected live pilot or the new raw-source boundary.
Documentation whitespace check: `git diff --check`, exit 0.
Independent fresh-context review: no high-confidence actionable findings in the pilot instructions or authority records.
The review confirmed author-funded escrow, separate author approval, required disclosure, running deadlines, and preparation-only status.

No runtime, released executor, ledger, scheduler, credential, or agent genome changed.
No agent was launched and no GitHub message or transaction was submitted.
Lean check: use existing identities and manual session facilities; no new launcher, transcript service, or payment mechanism.
Decision: Not ready for live pilots. S-01C/S-03A/B raw-source integration and S-71/S-80 persistence and live-task evidence remain missing.
