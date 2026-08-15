# Verification: WEA vNext S13C Financial Correction

**Version:** 1.1
**Date:** 2026-08-15
**Status:** Ready and merged

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
| S-13C.4 financial rejection | unknown row, unknown position, negative result, invalid transfer, invalid opening, malformed posting, and row-collision tests | PASS; state remains unchanged. |
| S-13C.5 replay and reconstruction | exact replay, identity conflict, opening-root, group-chain, separate reconstruction, cache repair, cardinality/byte ceilings, clean reconstruction, and tamper tests | PASS; no duplicate group, reordered history, modified opening evidence, caller mutation, or unbounded input is accepted. |
| Scenario promotion | `test_scenario_registry.py` | PASS; 70 current scenarios and no accepted-future scenario. |
| Runtime isolation | `test_runtime_boundary.py`; refreshed code graph | PASS; the module has no current closure reference or non-test inbound caller. |

## Fresh commands

| Command or check | Exit / result | Material evidence |
| --- | --- | --- |
| `python -m pytest tests/vnext/test_correction.py tests/vnext/test_scenario_registry.py tests/vnext/test_runtime_boundary.py -q` | 0 | `45 passed`. |
| `python -m pytest tests/vnext -q` | 0 | `491 passed, 18 skipped`. |
| `PYTHONPATH=<worktree>/src; python -m pytest -q` | 0 | `4776 passed, 18 skipped, 11 xfailed`. |
| `python -m ruff check src/wea_vnext tests/vnext` | 0 | All checks passed. |
| `python -m pyright src/wea_vnext tests/vnext/test_correction.py` | 0 | 0 errors, 0 warnings. |
| `python -m compileall -q src/wea_vnext tests/vnext` | 0 | Syntax compilation passed. |
| `python scripts/check_invariant.py` | 0 | `19025 = 10000 + 9025`; invariant holds. |
| ledger schema, task-index schema, and doc sync | 0 | All checks pass. |
| `python scripts/check_pr_scope.py --diff-base origin/main` | 0 | 12 changed files, all within allowed scope. |
| protected commit diff and `git diff --check` | 0 | No current ledger, writer, executor, ruleset, workflow, or CLI change; whitespace clean. |
| refreshed code graph and inbound trace | complete | `apply_financial_correction` has zero non-test inbound callers. |
| 64 sequential state-neutral correction groups | 0 | The accepted maximum, 64 groups and 128 rows, completed in 4.002 seconds. |
| GitHub PR `#943` checks on `73c2a72` | 0 | Scope, doc sync, Semgrep, vNext boundary, and Workers Builds all passed before merge. |

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
- GitHub CI passed on the exact reviewed head before publication.

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

Pass 1 found no actionable defect. Pass 2 found the signed-supply error fixed in
`734eabc`; pass 3 reviewed that correction clean. Subsequent fresh-context OLED
reviews exposed root/ordering, replay-cache, mutation, resource-bound, and
verification gaps. Every accepted finding below was reproduced, fixed, and
covered. The final fresh-context review of the current tree returned `No
findings`. The required `codex exec review --base origin/main` also found no
actionable defect and independently reran all 45 focused tests.

| Severity | Finding | Resolution |
| --- | --- | --- |
| P1 / HIGH | Burn-only corrections could not make the signed cumulative supply adjustment negative. | Fixed: only the resulting supply must remain non-negative; burn-only and signed-opening regressions pass. |
| HIGH | Reordered published rows or added authority bindings could establish a different opening root. | Fixed: the exact ordered opening evidence is committed by `opening_snapshot_hash`; both tamper regressions pass. |
| HIGH | State-neutral correction groups could be reordered with their idempotency records. | Fixed: every group commits to its sequence and predecessor, anchored at the opening snapshot; coordinated reorder is rejected. |
| HIGH | Approval hashes do not authenticate an untrusted Python caller. | Rejected for this approved inactive boundary: configured authority bindings are pre-verified trusted inputs and `confirm_correction` snapshots them. The module has no external effect and explicitly defers authenticated production source loading to live cutover. |
| MEDIUM | Repeated tuple copying and full replay made sequential history growth unavailable. | Fixed: row construction accumulates linearly; Spec/Design 1.1 bound one snapshot to 64 groups and all public input cardinalities plus 64 MiB aggregate published bytes. The maximum-chain probe completes in 4.002 seconds. |
| MEDIUM | R-FC-01 said only published rows while the accepted design and tests allow prior correction rows. | Fixed as a spec reconciliation: R-FC-01 now names known opening or accepted correction rows, matching Outcome and Design authority. |
| P2 | The permanent boundary pointed only to the parent spec, whose pre-delivery S-13C status is stale after this promotion. | Fixed: the boundary now links this accepted delta and states its priority over conflicting parent status and count text. |
| HIGH | A mutated nested group or derived replay cache could pass an exact-replay shortcut; identical-value subclasses were not rejected. | Fixed: every public operation reconstructs a separate exact state through full historical replay. Nested tampering/subclasses reject and a cache-only mutation is repaired. |
| HIGH | Revalidating by calling `__post_init__` in place mutated caller-owned frozen state even when an operation rejected. | Fixed: validation constructs a separate state. Rejection preserves original tuple/cache identities; exact replay returns an equal validated value. |
| MEDIUM | Public generators were materialized before limits, and count-only published-row bounds still allowed excessive bytes. | Fixed: every public iterable stops at limit plus one; aggregate published content rejects incrementally above 64 MiB. |
| MEDIUM | Binding uniqueness on `binding_id` alone prevented stable-ID version history. | Fixed: uniqueness uses `(binding_id, binding_version)`; canonical rotation evidence is covered. |
| GAP | R-FC-05 ceiling behavior and S-13C.4 row collision lacked direct tests. | Fixed: the suite builds a real 64-group chain, proves replay at the ceiling and atomic rejection of a 65th group, and forces a deterministic row-ID collision. |

## Protected lean cut

- Calibration preserved exact opening evidence, dual trusted authority inputs,
  atomic financial invariants, deterministic replay, tamper rejection, and the
  inactive runtime boundary.
- `delete`: nothing outside the accepted S-13C contract remains.
- `reuse`: sharing private canonicalization from Domain/Access was rejected
  because it would couple separate control planes without a public primitive.
- `stdlib` and `native`: the implementation already uses only Python standard
  library facilities and no external runtime.
- `yagni` and `shrink`: no safe cut remains. Removing strict separate rebuilds,
  root/chain commitments, explicit resource ceilings, or focused evidence would
  weaken a protected trust/data boundary.
- The derived replay cache, linear accumulator, and accepted snapshot ceilings
  are the smallest safe response to measured history growth without trusting
  mutable Python object identity; all affected checks were rerun.

## Completion decision

`Ready and merged`. The implementation contract, local checks, independent
review, Codex review, and exact-head CI are green. PR `#943` was squash-merged
as `942998d` on 2026-08-15.

## Completion ceiling

This evidence supports current inactive scenario status only. It does not
support live activation, current-ledger correction, durable atomicity, crash
recovery, or authenticated production authority loading.
