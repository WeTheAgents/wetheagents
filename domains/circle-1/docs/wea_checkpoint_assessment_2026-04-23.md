# WEA checkpoint assessment — 2026-04-23

Checkpoint sha: `c07e079`

This document records the findings from the first machine-produced WEA circle-1
checkpoint and selects the first hardening cut.

## Baseline findings

The full baseline is in `wea_baseline_memo.md`. The checkpoint at `c07e079`
confirms its structural readings. Key facts for routing:

| Dimension | Declared | Enforced | Exercised | Coldness gap |
|---|---:|---:|---:|---|
| Contract surface | 4 | 3 | 2 | Cohort compliance not yet measured |
| Enforcement surface | 4 | 4 | 3 | Not yet mapped to circle-1 model |
| **Module grammar** | **2** | **1** | **2** | **No declared zone templates** |
| Boundary contracts | 2 | 2 | 2 | Error topology partial |
| Observability discipline | 1 | 0 | 1 | No frozen output policy |
| Hardening loop | 4 | 3 | 3 | No circle-1 ↔ Gauntlet routing rule |

## Module grammar raw signals at c07e079

Two zones have visible empirical shapes, but no declared zone template that the
checkpoint tool can inspect.

| Zone | Files | Dominant shape | Share |
|---|---:|---|---:|
| `scripts/` | 119 | docstring + functions + main_guard + no_classes + no_future_annotations | 0.783582 |
| `src/wea_cli/` | 20 | docstring + functions + no_main_guard + no_classes + future_annotations | 0.65 |

A checkpoint tool scanning at `c07e079` can only report empirical shape statistics.
It cannot distinguish "no template declared" from "template declared but files drift".

## Why module grammar is the right first cut

From the baseline analysis three coldness gaps are equally compelling: module
grammar, boundary contracts, and observability discipline. Module grammar is
selected first because:

1. **Safest structural footprint.** No mass rewrites required. Declaring templates
   changes metadata, not behavior.
2. **Directly tied to agents' daily context.** The two measured zones are the ones
   agents edit most. Reducing shape guessing compounds across every code task.
3. **Lowest redundancy risk.** Zone templates replace ad-hoc oral shape memory,
   not an existing declared surface. The redundancy argument is clean.
4. **Unblocks the metric.** `module_grammar_uniformity` cannot be stable until
   the declared template exists. Observability and boundary contracts can wait
   for the metric to exist.

## Selected first cut

**Issue #780**: Declare canonical zone templates for `scripts/` and `src/wea_cli/`.

Deliverables:
- `scripts/.zone-template.yaml` — required/optional/forbidden shape for scripts/
- `src/wea_cli/.zone-template.yaml` — required/optional/forbidden shape for src/wea_cli/
- `scripts/score_repo.py` — checkpoint scorer that detects declared templates
- `tests/test_score_repo.py` — targeted tests proving detection signal

Expected metric shift after merge:
- `module_grammar.declared`: `2 → 3` (partial → repeatable)
- `module_grammar_uniformity`: becomes a stable declared-template conformance ratio
  rather than an empirical dominant-shape share
- `new_file_conformity_rate`: enabled once a code task creates a new file in either zone

## What this cut does NOT do

- No CI gate wired for conformance (enforced stays at 1)
- No mass conformance rewrite of existing files
- No changes to boundary contracts, observability policy, or hardening loop routing
- No gauntlet involvement (additive work, redundancy proof not required here)

## Monitoring window

Immediate rescan after merge should show `module_grammar.declared = 3` and
`template_declared: true` for both zones.

Follow-up: rescan after the next 3 accepted code tasks touching either zone, or
after 14 days if none appear. Monitor `module_grammar_uniformity` for new-file drift.
