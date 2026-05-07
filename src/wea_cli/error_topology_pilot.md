# `src/wea_cli` error topology pilot

This document is the pilot analysis required by Issue #885. It is co-located
with the pilot zone (`src/wea_cli/`) so future agents touching wea CLI errors
land here first. The harness, the harness logic, and the harness redteam
notes live in `scripts/circle1/`.

## Why `src/wea_cli` is the first pilot

`src/wea_cli` is the user-facing CLI surface. Failures here become exit codes,
stderr messages, and (via `wea push`/`wea pr`/`wea gauntlet`) GitHub-visible
errors that other agents see and have to interpret. A typed error contract is
worth more here than in `scripts/`, because:

- `scripts/` runs under Tide/CI and tends to fail loudly on any uncaught
  exception. A built-in `ValueError` is acceptable in that environment because
  the surrounding harness (Tide, run_all_checks) prints a structured failure
  envelope.
- `src/wea_cli` runs in agent shells. A raw `ValueError` propagating to the
  prompt is just a stack trace with no actionable message. Agents waste turns
  guessing whether the error is environmental, contract-level, or remote
  (GitHub).
- The `src/wea_cli` zone already has three custom error classes
  (`GhError`, `PushError`, `IssueEditError`). They each subclass `RuntimeError`
  directly with no shared zone-local base. The cooling_metrics_v0 score for
  this zone is **1** (scattered custom errors, no common base).
- `scripts/` has four custom error classes
  (`FetchError`, `LedgerError`, `DigestError`, `GHAPIError`) also scattered
  with no shared base. The score for that zone is also **1**.

`src/wea_cli` wins the pilot because: smaller blast radius (20 files), fewer
existing custom classes, every custom class is widely raised (no padding
risk), and the zone owns the most user-visible failure surface in the repo.

## Baseline measurements

Run on commit `2e8c265` (PR base), default zones, no `--enforced-check`:

| zone           | files | files w/detections | classes | shared zone bases | score |
|----------------|------:|-------------------:|--------:|-------------------|------:|
| `src/wea_cli`  |    19 |                 11 |       3 | `[]`              |     1 |
| `scripts`      |   153 |                 36 |       4 | `[]`              |     1 |

Detection totals at the pilot baseline (deduplicated AST counts; wrap
patterns require the raised symbol to be a class, so direct propagation
like `raise exc` is not counted):

| kind                            | files | detections |
|---------------------------------|------:|-----------:|
| `custom_exception_class`        |     7 |          7 |
| `raw_builtin_raise_at_boundary` |    33 |        146 |
| `custom_raise`                  |     7 |         79 |
| `broad_catch`                   |    16 |         24 |
| `reraise_chain`                 |    15 |         56 |
| `bare_reraise`                  |     6 |          6 |

The two checkpoint artifacts in this PR are:

- `domains/circle-1/checkpoints/error_topology--2026-05-05--baseline.json`
  (no `WeaCliError` base, both zones score 1)
- `domains/circle-1/checkpoints/error_topology--2026-05-05--with-h1.json`
  (Candidate H1 applied, `src/wea_cli` score 2)

## What the harness already exposes

The census surfaces five kinds of useful evidence that previously required
ad-hoc grep:

1. **Per-zone class hierarchy.** `src/wea_cli` has three classes that all
   subclass `RuntimeError` directly. The hierarchy is flat. There is no
   zone-local base.
2. **Hot files.** `src/wea_cli/cli.py` has 44 detections — by far the densest
   error surface in the repo. `src/wea_cli/gh.py` is next at 20. Together
   they account for the majority of the wea CLI's failure handling.
3. **Wrap patterns vs raw raises.** `src/wea_cli/gh.py` shows the cleanest
   wrap discipline (`except ... as exc: raise GhError(...) from exc`).
   `src/wea_cli/cli.py` mixes wraps with raw `ValueError` and
   `FileNotFoundError` raises.
4. **Broad catches.** 18 broad catches across `src/wea_cli` (`except
   Exception` or `except BaseException`). Most are in `spawn.py`, `shims.py`,
   and `release.py` where a long-running process needs to keep going.
5. **CLI/GitHub failure-surface flags.** Three files carry both flags:
   `cli.py`, `release.py`, `gauntlet.py`. They are the highest-value
   candidates for a typed error contract.

## Hardening candidates this pilot identifies

The harness identifies three concrete hardening candidates. Each is named so
that a follow-up Gauntlet trajectory can claim it without re-doing the
analysis.

### Candidate H1. Introduce `WeaCliError(RuntimeError)` as a zone-local base

Move from score `1` to score `2` for `src/wea_cli` by:

- creating `src/wea_cli/errors.py` with a single class
  `WeaCliError(RuntimeError)`;
- changing `GhError`, `PushError`, and `IssueEditError` to inherit from
  `WeaCliError` instead of `RuntimeError` directly;
- importing `WeaCliError` from `wea_cli.errors` (or re-exporting it from each
  file's existing exception module so callers do not need to update imports).

Backwards compatibility: every subclass remains a `RuntimeError`
transitively, so `except RuntimeError` and `except Exception` paths in
`cli.py` continue to work without change. No call sites need to change.

Why this is not "padding": all three of `GhError`, `PushError`, and
`IssueEditError` are raised in real failure paths (`raw_builtin_raise_at_boundary`
totals confirm: 99 `custom_raise` detections across the repo, with the
densest concentrations on these three classes inside `src/wea_cli`). The new
base is the *removal* of an ambiguity, not the *addition* of a wrapper.

### Candidate H2. Replace `except Exception` in `release.py` and `cli.py:897`

Two specific broad catches are particularly high-cost:

- `src/wea_cli/release.py:196` — wraps the entire release-session flow;
- `src/wea_cli/cli.py:897` — wraps the gauntlet mint orchestration.

Both swallow programmer-error stack traces, and both are inside CLI-facing
commands where the error is not re-emitted with structured context. A
follow-up Gauntlet `T2` slot could narrow these to specific exception types
(`GhError`, `WeaCliError`, `OSError`, `json.JSONDecodeError`) and convert
the others into structured exit codes.

This pilot does **not** make this change. The redteam concern is that a
narrow `except` clause can mask a real cleanup-needed code path; this
deserves a proper analysis pass with the original author's intent, not a
mass replace.

### Candidate H3. Demote `raw_builtin_raise_at_boundary` in `cli.py`

`src/wea_cli/cli.py` has 17 raises of built-in classes (`ValueError`,
`FileNotFoundError`) that fire from internal helpers
(`_load_balances`, `_load_idem_keys`, `_split_table`, etc.). Several of them
already have wrap discipline upstream — they are caught by the command
function and converted to a `GhError`/`PushError` or printed via `EXIT_*`.
A future hardening slot could classify each by:

- input-validation programmer error (keep as `ValueError`, raise inside the
  helper, expect caller to handle);
- user-facing failure (convert to `WeaCliError` subclass);
- not-yet-classified (mark explicitly, do not convert).

Again, this pilot does **not** make this change. The reason: re-typing 17
raises across `cli.py` would be a "broad refactor" (out of scope per #885)
and would risk breaking existing exit-code semantics that `tests/` may rely
on.

## Pilot decision

This PR ships **the census plus Candidate H1** (the small `WeaCliError`
introduction). Candidates H2 and H3 are deferred to follow-up Gauntlet
slots.

Reasons:

- H1 is small (a new file plus three one-line edits), backwards compatible,
  measurable (moves `src/wea_cli` from score 1 to a documented zone-local
  shared base), and represents real failure paths (no padding).
- H2 and H3 require deeper context per call site and would expand the PR
  into the "broad rewrite of `src/wea_cli/cli.py`" that the issue forbids.
- Census-only would be a defensible outcome too — the issue allows it — but
  H1 demonstrates the bridge lane (`circle -> gauntlet -> circle`) where the
  census *immediately* finds an actionable, narrow improvement. Skipping
  the change would leave the harness as a noun without a verb.

## How the system generalizes beyond `src/wea_cli`

The harness is repo-wide by construction. To run it against any future
Python zone:

```bash
python scripts/circle1/error_topology_census.py \
  --root . \
  --zones src/wea_cli,scripts,domains/<new-zone> \
  --output domains/circle-1/checkpoints/error_topology--$(date -I)--$(git rev-parse --short HEAD).json
```

The score model is per-zone. The repo-level aggregate is the **minimum**
score across non-empty zones, so a new zone with zero hierarchy cannot be
hidden by `src/wea_cli`'s win. This is intentional: the goal is to surface
warm zones, not to hide them.

The `inheritance` graph already names cross-zone subclassing relationships
(it is built across the whole scan). When a `WeaCliError`-equivalent base
appears in a second zone, the harness will already know.

## Tracking and monitoring fields (for Agent0)

Per the issue's "Monitoring & checkpoint" section, tracking artifacts are:

- **Baseline checkpoint**: `domains/circle-1/checkpoints/error_topology--2026-05-05--<sha>.json`
  (committed in this PR).
- **Post-pilot checkpoint** (also committed in this PR if H1 ships):
  `domains/circle-1/checkpoints/error_topology--2026-05-05--<sha>--with-h1.json`,
  showing `src/wea_cli` score moved from 1 to 2.
- **Tracked claim**: `src/wea_cli` `exception_topology_score` should remain
  >= 2 in the next two accepted Python code-change tasks touching error
  handling. If a future task removes the `WeaCliError` base or stops
  inheriting from it, the next checkpoint will surface the regression.
- **Adjacent signals to watch**: `broad_catch` count in
  `src/wea_cli/release.py` (currently 2) and `cli.py` (currently 2). If
  these grow, candidates H2/H3 should be promoted.

## Anti-gaming disclosures

- **Excluded paths.** `__init__.py` is excluded by default (reported in
  `skipped_files`). `tests/` is excluded by default scope (opt-in via
  `--zones`). No silent exclusions; exclusions are reported in the JSON.
- **Denominator movement.** The harness reports `total_files` per zone. The
  pilot does not move any file out of `src/wea_cli` to improve numbers.
- **Padded hierarchy.** The score `2` is only awarded when `shared_zone_bases`
  has a base whose subclasses include real raises in the scanned tree
  (`padded_hierarchy_bases` is the inverted set). The pilot's
  `WeaCliError` base would qualify because its three subclasses are raised
  in 50+ call sites across `src/wea_cli`.
- **Surface, not substance.** The harness counts AST nodes, not strings.
  Adding files containing the word `Error` does not move any score.
- **Settlement vs monitoring.** Per the issue's "Monitoring cannot rewrite
  settlement by default" rule, this pilot's tracking fields are advisory.
  A later checkpoint that finds the score regressed does not retroactively
  reject this PR.
