# Verification: WEA vNext S13C Financial Correction

**Version:** 1.0
**Date:** 2026-08-15
**Status:** Corrected implementation independently reviewed clean; CI pending

Decision: `S13C implemented as an inactive control plane; not live`.

`BDD alignment: 100% for current S-13C.1 through S-13C.5 evidence.`

## Accepted boundary

- Exact proposal and approval hashes bind every accepted input.
- One effective operator source and one independent effective Agent0 source
  approve the same proposal hash.
- Transfer, mint, and burn postings append as one immutable group or not at all.
- The financial invariant passes before and after each complete group.
- Prior published bytes stay unchanged; replay is deterministic and
  idempotent; reconstruction rejects tampering.
- The implementation has no live writer, persistence, runtime, CLI, executor,
  ruleset, GitHub, or current-ledger integration.

## Scenario evidence

| Scenario | Evidence | Result |
| --- | --- | --- |
| S-13C.1 atomic redistribution | `test_s_13c_1_atomic_redistribution_preserves_published_row_bytes` | PASS; two deterministic rows append after the exact published-row prefix. |
| S-13C.2 supply correction | mint/burn sequence, burn-only, and signed-opening tests | PASS; position totals and signed total minted move together while resulting supply stays non-negative. |
| S-13C.3 approval boundary | missing, mismatch, independence, unknown, inactive, and premature tests | PASS; invalid evidence returns no group. |
| S-13C.4 financial rejection | unknown row, unknown position, negative result, invalid transfer, invalid opening, and malformed posting tests | PASS; state remains unchanged. |
| S-13C.5 replay and reconstruction | exact replay, identity conflict, clean reconstruction, and tamper tests | PASS; no duplicate group and modified evidence is rejected. |
| Scenario promotion | `test_scenario_registry.py` | PASS; 70 current scenarios and no accepted-future scenario. |
| Runtime isolation | `test_runtime_boundary.py`; refreshed code graph | PASS; the module has no current closure reference or non-test inbound caller. |

## Fresh commands

| Command or check | Exit / result | Material evidence |
| --- | --- | --- |
| `python -m pytest tests/vnext/test_correction.py tests/vnext/test_scenario_registry.py tests/vnext/test_runtime_boundary.py -q` | 0 | `31 passed`. |
| `python -m pytest tests/vnext -q` | 0 | `477 passed, 18 skipped`. |
| `PYTHONPATH=<worktree>/src; python -m pytest -q` | 0 | `4762 passed, 18 skipped, 11 xfailed`. |
| `python -m ruff check src/wea_vnext tests/vnext` | 0 | All checks passed. |
| `python -m pyright src/wea_vnext tests/vnext/test_correction.py` | 0 | 0 errors, 0 warnings. |
| `python -m compileall -q src/wea_vnext tests/vnext` | 0 | Syntax compilation passed. |
| `python scripts/check_invariant.py` | 0 | `19025 = 10000 + 9025`; invariant holds. |
| ledger schema, task-index schema, and doc sync | 0 | All checks pass. |
| `python scripts/check_pr_scope.py --diff-base origin/main` | 0 | 12 changed files, all within allowed scope. |
| protected commit diff and `git diff --check` | 0 | No current ledger, writer, executor, ruleset, workflow, or CLI change; whitespace clean. |
| refreshed code graph and inbound trace | complete | `apply_financial_correction` has zero non-test inbound callers. |

The Pyright installation reports one pre-existing unrecognized configuration
setting and an available newer version. It still completed with zero errors and
zero warnings. Pytest reports the repository's existing asyncio fixture-scope
deprecation warning. Neither warning is caused by this change.

## Scope evidence

- Intended production addition: `src/wea_vnext/financial_correction.py` only.
- Intended contract additions: this OLED change and focused vNext tests.
- Intended durable documentation edit: `docs/VNEXT_BOUNDARY.md`.
- Current `ledger/`, v1 code, executor closures, manifests, rulesets, and CLI
  entrypoints are unchanged.
- The commit-aware PR-scope check passes for all 12 changed files. The protected
  ledger/runtime diff is empty.
- GitHub CI remains the final publication gate.

## Self-roast

- Actual request: yes. The change implements the separately approved S13C
  correction lane and does not add the rejected reference runtime.
- Scope: narrow by boundary. The only production file is the new inactive
  module; the protected ledger, writer, executor, ruleset, workflow, and CLI
  diff is empty.
- Current contracts: preserved. The complete repository suite and the live v1
  invariant pass.
- Risk evidence: appropriate. Tests cover money kinds, approval independence,
  active bindings, atomic failure, replay conflicts, exact bytes, and tampered
  reconstruction.
- BDD change: intentional. Only S-13C moves from accepted-future to current;
  the 69 prior current IDs remain present.
- Live/research isolation: explicit. There is no inbound production caller and
  no persistence or external effect.

The review found and corrected one fail-closed construction issue before this
record: opening positions are now rebuilt before their canonical sort, so a
malformed caller object cannot escape as a raw attribute failure.

## Independent review

Pass 1 found no actionable defect. Pass 2 found one P1 contract error: the code
required cumulative `total_minted` to remain non-negative, but the accepted
contract defines it as a signed supply adjustment and requires only
`opening_supply + total_minted` to remain non-negative. The invariant and
opening-state validation now implement that rule. Burn-only and signed-opening
regressions pass, along with the complete verification matrix. Pass 3 reviewed
corrected head `734eabc`, reran all 31 focused tests, and reported no actionable
defect. One final exact-head review follows this documentation-only record.

## Completion ceiling

This evidence supports current inactive scenario status only. It does not
support live activation, current-ledger correction, durable atomicity, crash
recovery, or authenticated production authority loading.
