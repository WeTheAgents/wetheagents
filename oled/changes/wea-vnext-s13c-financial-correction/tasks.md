# Tasks: WEA vNext S13C Financial Correction

**Version:** 1.0
**Date:** 2026-08-15
**Status:** Approved for execution
**Outcome:** `outcome.md` version 1.0
**Specification:** `spec.md` version 1.0
**Design:** `design.md` revision 1.0

## Group 1 — Lock the executable contract

- [x] Add failing `tests/vnext/test_correction.py` coverage for S-13C.1 through
  S-13C.5, including exact replay, conflicting identities, atomic failure,
  approval binding, reconstruction, and tamper rejection.
- [x] Update the scenario-registry contract to promote only S-13C, increase the
  current count from 69 to 70, and leave no accepted-future scenario.
- [x] Extend the runtime-boundary contract so the correction module cannot
  enter an executor or pre-activation entrypoint closure.
- [x] Run the focused tests and record the expected red result before adding
  production code.

## Group 2 — Implement the inactive correction control plane

- [x] Add `src/wea_vnext/financial_correction.py` with exact immutable opening
  evidence, proposal, posting, approval, row, group, idempotency, and state
  types.
- [x] Implement canonical hashes, strict type reconstruction, authority
  resolution, and opening-state invariant validation.
- [x] Implement atomic application for transfer, mint, and burn postings with
  deterministic rows and correction groups.
- [x] Implement exact replay and conflict behavior.
- [x] Reconstruct every supplied state from opening evidence and reject
  modified proposals, approvals, rows, hashes, ordering, or invariants.
- [x] Keep the module outside all current runtime and ledger-write paths.

## Group 3 — Reconcile durable evidence

- [x] Make all focused S13C, scenario-registry, and runtime-boundary tests green.
- [x] Re-index repository code intelligence and verify the new module has no
  executor, CLI, current-ledger, or network path.
- [x] Add `HANDOFF.md` with the exact inactive boundary, remaining live-cutover
  work, and safe continuation instructions.
- [x] Add `verification.md` with exact commands and fresh results.
- [x] Mark this checklist only from observed evidence.

## Group 4 — Verify and publish

- [x] Run focused verification:

  ```powershell
  python -m pytest tests/vnext/test_correction.py tests/vnext/test_scenario_registry.py tests/vnext/test_runtime_boundary.py -q
  ```

- [x] Run all vNext and repository tests:

  ```powershell
  python -m pytest tests/vnext -q
  python -m pytest -q
  ```

- [x] Run static, syntax, invariant, schema, documentation, and scope gates:

  ```powershell
  python -m ruff check src/wea_vnext/financial_correction.py tests/vnext/test_correction.py tests/vnext/scenarios.py tests/vnext/test_scenario_registry.py tests/vnext/test_runtime_boundary.py
  python -m pyright src/wea_vnext/financial_correction.py tests/vnext/test_correction.py
  python -m compileall -q src/wea_vnext/financial_correction.py tests/vnext/test_correction.py
  python scripts/check_invariant.py
  python scripts/check_ledger_schema.py
  python scripts/check_task_index_schema.py
  python scripts/check_doc_sync.py
  python scripts/check_pr_scope.py --diff-base origin/main
  ```

- [x] Inspect `git status`, `git diff --check`, branch-only commits, and the
  protected-file diff. Keep the stage set limited to S13C.
- [x] Perform the required self-roast for task alignment, scope, contracts,
  tests, and research/live isolation.
- [ ] Commit and push the dedicated branch, open one draft PR, and wait for all
  required checks.
- [ ] Run `codex exec review`, fix every actionable finding, and repeat until
  clean.
- [ ] Mark the PR ready and merge only after local verification, review, and CI
  are clean.

## Completion ceiling

Completion means S-13C is a tested current inactive control-plane scenario.
It does not mean that WEA vNext is live, that the current ledger can be
corrected through this API, or that a durable financial transaction boundary
exists.
