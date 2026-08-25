# Tasks: WEA vNext S13C Financial Correction

**Version:** 1.4
**Date:** 2026-08-17
**Status:** S13C implementation and SDD reconciliation complete. Downstream
Block 9 Design 1.0/1.1 and Tasks 2.0/2.1 are exact-accepted; dormant Groups 1,
3, 4, and 5 are implemented and verified. The public-after-private-tests path
is selected. Group 2 waits for exact Design 1.2 acceptance, Tasks 2.2, and later
exact environment-package approvals.
**Outcome:** `outcome.md` version 1.0
**Specification:** `spec.md` version 1.1
**Design:** `design.md` revision 1.1

## Version history

| Version | Date | Meaning |
| --- | --- | --- |
| 1.0 | 2026-08-15 | Initial implementation checklist. |
| 1.1 | 2026-08-15 | Added review-driven tamper, authority-version, and resource-bound work. |
| 1.2 | 2026-08-16 | Reconciles post-merge SDD evidence and adds the operator approval package. |
| 1.3 | 2026-08-16 | Records all five operator decisions and prepares the Block 9 BDD review gate. |
| 1.4 | 2026-08-17 | Records exact Block 9 Outcome/Spec 1.0 acceptance and opens Design only. |

## Group 1 — Lock the executable contract

- [x] Add failing `tests/vnext/test_correction.py` coverage for S-13C.1 through
  S-13C.5, including exact replay, conflicting identities, atomic failure,
  approval binding, reconstruction, and tamper rejection.
- [x] Update the scenario-registry contract to promote only S-13C and increase
  the current count from 69 to 70. The later accepted Block 9 BDD tracks 9
  accepted-future scenarios without changing current S13C behavior.
- [x] Extend the runtime-boundary contract so the correction module cannot
  enter an executor or pre-activation entrypoint closure.
- [x] Close evidence decision `SDD-01`: the original chronological RED output
  was not retained. A retrospective baseline check proves that the exact S13C
  test module cannot load on pre-S13C source because
  `wea_vnext.financial_correction` is absent. Operator approval is required to
  accept that limitation. The operator accepted it on 2026-08-16 and did not
  claim that the missing output exists.

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
- [x] Bind reconstruction to an ordered opening-snapshot commitment and chain
  every group to its sequence position and predecessor.
- [x] Bound public iterables and aggregate opening-row bytes before unbounded
  materialization, then cap one inactive snapshot at 64 correction groups.
- [x] Validate into a separate reconstructed state so rejected operations never
  mutate caller-owned tuples or derived replay state.
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
- [x] Commit and push the dedicated branch and open one draft PR. Wait for all
  required checks.
- [x] Run `codex exec review`, fix every actionable finding, and repeat until
  clean.
- [x] Mark the PR ready and merge only after local verification, review, and CI
  are clean.

## Group 5 — Post-merge SDD reconciliation and operator review

- [x] Add append-only Outcome, Spec, Design, Tasks, and Verification version
  provenance without changing accepted behavior.
- [x] Express S-13C.1 through S-13C.5 as explicit GIVEN/WHEN/THEN/EVIDENCE
  scenarios and map every independent requirement clause to exact test IDs.
- [x] Add focused tests for complete canonical proposal inputs, exact payload
  hash, zero delta, unique approval roles, and exact binding-version evidence.
- [x] Mark stale parent Domain/Access status as historical and point to the
  current S13C delta and review package.
- [x] Build one self-contained Russian HTML artifact with plain explanations,
  a locked accepted-decision record, Block 9 BDD, and exportable approval text.
- [x] Record the already merged PR `#943` (`942998d`) and final verification PR
  `#944` (`0ea6513`) as provenance.
- [x] Record operator acceptance of `SDD-01`, `SDD-02`, `OD-28`, `OD-29`, and
  `NEXT-01` on 2026-08-16.
- [x] Record separate operator acceptance of exact Block 9 Outcome/Spec 1.0
  without changes on 2026-08-17.

## Completion ceiling

Completion means S-13C is a tested current inactive control-plane scenario.
It does not mean that WEA vNext is live, that the current ledger can be
corrected through this API, or that a durable financial transaction boundary
exists.

Post-merge SDD reconciliation is complete. The current downstream gate is exact
review of proposed Block 9 Design 1.2. Tasks 2.2 may be prepared only after its
acceptance. Environment mutation and live cutover remain separate gates.
