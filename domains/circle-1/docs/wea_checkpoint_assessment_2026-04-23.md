# WEA checkpoint assessment — 2026-04-23

Baseline checkpoint: commit `c07e079`.

## Baseline module_grammar scores (tool-measured)

| Dimension | Declared | Enforced | Exercised |
|---|---:|---:|---:|
| module_grammar | 1 | 0 | 2 |

Source: `domains/circle-1/checkpoints/wea--2026-04-23--c07e079.json`

## Raw signals

| Zone | Files | Conforming | Dominant shape rate | Template declared |
|---|---:|---:|---:|---|
| `scripts/` | 129 | 120 | 0.930 | No |
| `src/wea_cli/` | 19 | 17 | 0.895 | No |

**Empirical dominant shape — `scripts/`:** module docstring + `from __future__ import annotations` + `if __name__ == '__main__'` guard.

**Empirical dominant shape — `src/wea_cli/`:** module docstring + `from __future__ import annotations`, no `__main__` guard (library modules).

Non-conforming files:
- `scripts/`: `audit_branch_entropy.py`, `check_idem_key_format.py`, `check_orphan_escrows.py`, `economy_constants.py`, `io_helpers.py`, `ledger_ops.py`, `pipeline_parser.py`, `tide_ops.py` (missing `future_annotations` or `main_guard`)
- `src/wea_cli/`: `cli.py`, `shims.py` (contain `if __name__ == '__main__'` — violates library zone shape)

## Baseline interpretation

**Why declared=1 (ad hoc, tool-measured):**

At `c07e079`, the two zones showed strong empirical conformance — but with no canonical template files on disk, the measurement tool cannot distinguish "accidental convergence" from "intentional declared grammar". The holistic baseline memo (`wea_baseline_memo.md`) scored `declared=2` because `docs/style_guide.md` documents patterns in prose. The tool-based score is narrower: it only considers explicit zone template files.

**Why exercised=2 (partial):**

Both zones have strong empirical conformance rates (~93% and ~89%), showing the shapes are alive in practice. The score stops at 2 rather than 3 because the paths are not yet enforced — no CI check or pre-commit hook validates conformance. "Exercised" without "enforced" is structural luck, not frozen discipline.

## Selected first cut: task #780

**Goal:** turn empirical shapes into declared grammar.

**Implementation:**
1. Declare canonical zone templates as machine-readable JSON files in `domains/circle-1/zone_templates/`.
2. Create `scripts/score_repo.py` — a scanner that detects template presence and measures conformance.
3. Create `scripts/circle1/zone_grammar.py` — the core detection logic usable from tests.

**Expected metric shift after task #780:**

| Dimension | Before | After | Change |
|---|---:|---:|---|
| module_grammar.declared | 1 | 3 | repeatable: both zones have canonical templates |
| module_grammar.enforced | 0 | 0 | unchanged — no CI check added in this cut |
| module_grammar.exercised | 2 | 3 | avg conformance ≥ 90% triggers exercised=3 |

**What this does NOT do:**
- Does not rewrite non-conforming files (that is a future conformance ratchet task).
- Does not add CI enforcement (that is the next step after templates are stable).
- Does not address boundary contracts, observability, or error topology gaps.

**Redundancy proof:**
Ad hoc local shape memory for `scripts/` and `src/wea_cli/` (currently scattered across `docs/style_guide.md` and team oral tradition) is made less necessary by the canonical template files and the scanner. Future agents adding files to either zone can consult the template instead of reading existing files empirically.

## Next checkpoint

Rescan after this task is merged to confirm:
- `module_grammar.declared` moves to 3
- `zones_with_declared_templates` shows both `scripts` and `src_wea_cli`
- `zone_signals.*.basis` changes from `empirical` to `declared`

Command:
```
python scripts/score_repo.py --root . --target wea --scan-date <date> --repo-sha <sha>
```
