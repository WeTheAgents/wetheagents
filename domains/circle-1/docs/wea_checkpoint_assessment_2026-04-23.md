# WEA circle-1 checkpoint assessment — 2026-04-23 (SHA c07e079)

## Checkpoint findings

Scan performed on WEA repo at SHA c07e079 (2026-04-23).
Full record: `domains/circle-1/checkpoints/wea--2026-04-23--c07e079.json`.

### Structural scores

| Dimension | Declared | Enforced | Exercised |
|---|---|---|---|
| contract_surface | 3 | 3 | 3 |
| enforcement_surface | 3 | 3 | 3 |
| **module_grammar** | **1** | **0** | **1** |
| boundary_contracts | 2 | 1 | 2 |
| observability_discipline | 1 | 1 | 2 |
| hardening_loop | 3 | 3 | 3 |

### module_grammar raw signals

| Zone | File count | Dominant shape share | Template declared |
|---|---|---|---|
| `scripts/` | 129 | **0.783582** | false |
| `src/wea_cli/` | 20 | **0.65** | false |

`contract_surface` and `enforcement_surface` are already saturated on Phase 1 checks.
`module_grammar` is the clearest remaining gap: strong empirical uniformity exists in
both zones, but no declared template surface exists for a future checkpoint to compare against.

## Selected first cut: declare zone templates

### Why this cut

1. **Narrowest possible intervention.** Two JSON template files, no existing code touched.
2. **Direct metric shift.** Converts `module_grammar.declared` from 1 (ad hoc) to 3 (repeatable).
3. **Enables `new_file_conformity_rate`.** Once templates exist, a checker can compare
   new files against a declared shape instead of an empirical guess.
4. **Removes ad hoc shape memory.** Agents no longer need to inspect existing files to
   infer what a new script should look like; the template answers that question deterministically.

### Expected metric shift after this cut

| Signal | Before | After |
|---|---|---|
| `module_grammar.declared` | 1 | 3 |
| `module_grammar.enforced` | 0 | 0 (enforcement deferred — gate requires templates to stabilize first) |
| `module_grammar.exercised` | 1 | 1 (unchanged until new files land using templates) |
| Measurement method | empirical dominant shape | declared template |

### Implementation scope

| File | Role |
|---|---|
| `domains/circle-1/templates/scripts_zone.json` | Zone template for `scripts/` |
| `domains/circle-1/templates/src_wea_cli_zone.json` | Zone template for `src/wea_cli/` |
| `scripts/score_repo.py` | CLI: detects template evidence, computes uniformity |
| `scripts/circle1/zone_template.py` | Detection + conformity helpers |
| `tests/test_score_repo.py` | Fixture-based tests for template-detection signal |

### What this cut does NOT do

- Does not rewrite existing files in `scripts/` or `src/wea_cli/`.
- Does not add a CI gate for conformance (next step after templates stabilize).
- Does not change issue templates, governance mechanics, or payout rules.

## Monitor window

- **Immediate:** rerun `score_repo.py` after merge — both zones must report `template_declared: true`.
- **After 3 accepted code-change tasks** touching either zone: check that new files follow the declared templates.
- **After 14 days** if no such tasks appear: schedule a follow-up review.
