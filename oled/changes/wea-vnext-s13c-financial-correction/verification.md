# Verification: WEA vNext S13C Financial Correction

**Version:** 1.4
**Date:** 2026-08-17
**Status:** Implementation merged; Block 9 BDD accepted; Design next

Decision: `S13C implemented as an inactive control plane; not live`.

`BDD alignment: 100% for current S-13C.1 through S-13C.5 evidence.`

## Artifact versions

| Artifact | Current version | Authority and status |
| --- | --- | --- |
| Outcome | 1.0 | Accepted by the WEA operator on 2026-08-15; behavior unchanged. |
| Specification | 1.1 | Accepted by the WEA operator on 2026-08-15; evidence map clarified on 2026-08-16. |
| Design | 1.1 | Accepted; no design change in this reconciliation. |
| Tasks | 1.4 | Exact Block 9 BDD acceptance recorded; Design next. |
| Verification | 1.4 | Current record for accepted SDD progression. |
| Operator review | `2026-08-17.1` | Self-contained HTML; six decisions accepted. |
| Block 9 Outcome/Spec | 1.0 | Accepted without changes on 2026-08-17 for Design; not implemented or live. |

Merged provenance: implementation PR `#943` was squash-merged as `942998d`.
Final verification record PR `#944` was merged as `0ea6513`. This reconciliation
audits the exact locally available `origin/main` commit `0ea6513`; no claim is
made that the unauthenticated remote was refreshed on 2026-08-16.

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
| Scenario promotion | `test_scenario_registry.py` | PASS for S13C; current registry target is 70 current / 9 accepted-future / 0 proposed-future Block 9 scenarios. |
| Runtime isolation | `test_runtime_boundary.py`; refreshed code graph | PASS; the module has no current closure reference or non-test inbound caller. |

The exact requirement-to-test map is in `spec.md` under **Verification
contract**. New direct tests cover empty and duplicate proposal inputs, exact
payload-hash binding, zero delta, duplicate approval roles, and a wrong binding
version.

## Task completion

| Required task | Evidence or authorized limitation | Result |
| --- | --- | --- |
| Implement accepted inactive S13C behavior | PR `#943`; production module; focused, vNext, and repository checks | PASS / merged. |
| Preserve runtime and ledger boundary | runtime-boundary tests, protected diff, no production inbound caller | PASS. |
| Close review findings | Finding table below and focused regressions | PASS. |
| Retain original chronological RED output | The original output was not retained. Retrospective pre-S13C import proof exists. | ACCEPTED limitation under `SDD-01`; no missing evidence is claimed. |
| Make accepted behavior and evidence transparent | Version logs, exact scenario map, current parent overlays, Russian HTML review | PASS. |
| Prepare the next project gate | Six operator decisions and accepted Block 9 Outcome/Spec 1.0 | PASS. Design is the next allowed gate. |

## Retrospective RED evidence and limitation

The original chronological RED command output is unavailable. We do not
recreate or backdate it. A later isolated baseline check loaded the exact
current `tests/vnext/test_correction.py` against pre-S13C source at
`d183a49fc32b8f4d1df244e0ffdc144066247941`. Python exited with code 1 and:

```text
ModuleNotFoundError: No module named 'wea_vnext.financial_correction'
```

This proves that the exact S13C test module distinguishes the pre-S13C tree.
It does not prove when the original RED run happened. Under `SDD-01`, the
operator accepted this missing timestamp/output as a historical evidence
limitation. The project does not claim that the missing record exists.

## Fresh acceptance-reconciliation commands — 2026-08-17

| Command or check | Exit / result | Material evidence |
| --- | --- | --- |
| `python -m pytest tests/vnext/test_correction.py tests/vnext/test_scenario_registry.py tests/vnext/test_runtime_boundary.py -q` | 0 | `53 passed`; direct requirement gaps are covered. |
| `python -m pytest tests/vnext -q` | 0 | `499 passed, 18 skipped`; the complete inactive vNext suite passes. |
| `python -m ruff check <review builder> tests/vnext/test_correction.py` | 0 | All checks passed. |
| `python -m pyright <review builder> tests/vnext/test_correction.py` | 0 | 0 errors and 0 warnings; the pre-existing config/version notices remain. |
| doc sync, economy invariant, ledger schema, and task-index schema | 0 | All pass; invariant remains `19025 = 10000 + 9025`. |
| `python build_sdd_review.py --check` | 0 | Source/status tokens, six locked accepted decision IDs, local links, fragments, unique IDs, exact contract hashes, and deterministic generated HTML all validate. |
| Playwright desktop/mobile review | 0 | Page has no console error; six accepted choices are checked and disabled, the exported record contains `BLOCK9-ACCEPT-01`, all nine Block 9 cards render, and 1280 px / 390 px viewports have no page overflow. |
| protected-path diff and `git diff --check` | 0 | No ledger, writer, CLI, workflow, executor, ruleset, or production-module edit; whitespace is clean. |

Pytest still reports the repository's existing asyncio fixture-scope warning.
It is unrelated to this reconciliation.

## Historical implementation commands — 2026-08-15

| Command or check | Exit / result | Material evidence |
| --- | --- | --- |
| `python -m pytest tests/vnext/test_correction.py tests/vnext/test_scenario_registry.py tests/vnext/test_runtime_boundary.py -q` | 0 | Historical merge evidence: `45 passed`; 2026-08-16 reconciliation adds direct contract cases and reruns this gate. |
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

2026-08-16 trigger decision: no new independent review was required. This
reconciliation changes documentation, direct evidence tests, and a local review
artifact only. It changes no money, authority, state, rollback, external API,
or production behavior. The serious implementation reviews below remain the
applicable independent evidence.

Pass 1 found no actionable defect. Pass 2 found the signed-supply error fixed in
`734eabc`; pass 3 reviewed that correction clean. Subsequent fresh-context OLED
reviews exposed root/ordering, replay-cache, mutation, resource-bound, and
verification gaps. Every accepted finding below was reproduced, fixed, and
covered. The final fresh-context review of the current tree returned `No
findings`. The required `codex exec review --base origin/main` also found no
actionable defect and independently reran all 45 focused tests then present.

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

- 2026-08-16 artifact cut: one self-contained generated HTML replaces a new
  parallel application or external dependency. It uses standard-library build
  and validation only. The older large Domain/Access review remains historical
  and is not duplicated into the current package.
- Current cuts rejected: removing source validation, local-link checks,
  explicit non-activation warnings, or exportable decision text would weaken
  review safety or operator usability.
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

## Evidence gaps and non-blocking limitations

- Blocking evidence decision: none. The original chronological RED output is
  absent, and the operator accepted that limitation under `SDD-01`.
- Blocking authority decision for actual Block 9 Design: none. Exact
  Outcome/BDD 1.0 was accepted without changes on 2026-08-17. Design must still
  stop for separate acceptance before implementation.
- Non-blocking environment limitation: the remote could not be fetched with
  noninteractive credentials on 2026-08-16. All current evidence is pinned to
  the exact locally available `origin/main` commit `0ea6513`.

## Completion decision

`Implementation ready and merged; Block 9 BDD accepted; Design next`.
The implementation contract, local checks, independent review, Codex review,
and exact-head CI are green. PR `#943` was squash-merged as `942998d` on
2026-08-15, and PR `#944` preserved final verification as `0ea6513`.

The operator accepted `SDD-01`, `SDD-02`, `OD-28`, `OD-29`, and `NEXT-01` on
2026-08-16, then accepted exact Block 9 Outcome/Spec 1.0 without changes on
2026-08-17. This authorizes Design only. It does not authorize implementation
or activate vNext.

## Completion ceiling

This evidence supports current inactive scenario status only. It does not
support live activation, current-ledger correction, durable atomicity, crash
recovery, or authenticated production authority loading.
