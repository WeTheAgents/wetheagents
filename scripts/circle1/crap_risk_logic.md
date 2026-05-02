# Circle-1 CRAP risk harness logic

## Purpose

This harness gives Agent0 a repeatable function-level review signal for Python
files under `scripts/` and `src/wea_cli/`. It does not reject code, mutate
ledger data, change Tide, or create a CI gate. It exists to make review
attention easier to aim.

## Actors

- Agent0 runs the harness during Circle-1 checkpoints or Python PR review.
- Worker agents read the top-risk report before touching risky functions.
- Future Circle-1 sweeps update tracking fields when a watched function later
  correlates with a review finding, bug, redteam note, hardening task, or test
  addition.

## Inputs

- Python source from `scripts/**/*.py` and `src/wea_cli/**/*.py`.
- Optional explicit coverage artifact: coverage.py JSON or Cobertura-style XML.
- Existing `scripts/circle1/observability_inventory.py` evidence for `scripts/`.

No coverage artifact means `coverage_state: unknown`. It never means zero
coverage and never means full coverage.

## Scoring States

- `known`: the supplied coverage artifact contains measured lines for the
  function span. The harness computes CRAP:
  `complexity^2 * (1 - coverage)^3 + complexity`.
- `unknown`: no artifact was supplied, or the artifact does not contain that
  file. CRAP is not computed. The fallback risk rule uses complexity plus
  side-effect weight.
- `not_applicable`: the artifact contains the file but no measured lines in the
  function span. CRAP is not computed because the denominator is absent.

Complexity source is `python_ast_cyclomatic_v0`: base 1 plus branches, loops,
exception handlers, boolean decision points, assertions, comprehensions, match
cases, conditional expressions, and lambdas. Nested functions are separate
review units.

## Observability Annotation

For functions in `scripts/`, the harness imports the #884 scanner and keeps only
channel evidence whose line number falls inside the function body. This avoids
marking a quiet helper risky only because another function in the same file
prints, writes a file, or calls GitHub.

Side-effect weights are advisory:

- 4: ledger/protocol writes and GitHub comment candidates.
- 3: subprocess and network calls.
- 2: file writes, stderr, and ambiguous side effects.
- 1: stdout and logging.
- 0: no function-local observability evidence.

## Output And Tracking

Each function entry carries:

`path`, `symbol`, `start_line`, `end_line`, `complexity`,
`complexity_source`, `coverage_state`, `coverage_percent`, `crap_score`,
`risk_band`, `risk_reason`, `observability_channels`, `side_effect_weight`,
`tracking_status`, `tracking_notes`, and `evidence_refs`.

Future sweeps should keep the same entry shape and update:

- `tracking_status`: `new`, `watched`, `correlated`, `retired`, or
  `inconclusive`.
- `tracking_notes`: short human note explaining the status.
- `evidence_refs`: compact refs such as PR numbers, issue numbers, review
  findings, redteam notes, bug fixes, hardening tasks, or test additions.

The committed pilot checkpoint is intentionally compact. It can omit
lower-priority functions while reporting how many were omitted.

## Invariants

- The scanner reads source and optional coverage artifacts only.
- It does not import scanned Python files.
- It does not execute scanned code.
- Missing coverage remains unknown.
- Nested files under the default include patterns are included.
- Parse errors are reported in summary instead of hidden.
- Observability absence must not crash risk scoring.
- CRAP is computed only with known coverage.

## Failure Paths

- Missing repo root: CLI exits non-zero.
- Missing coverage path: CLI exits non-zero.
- Unsupported or malformed coverage artifact: CLI exits non-zero.
- Read or parse errors in scanned files: report summary records the file and
  continues scanning other files.
- Missing `scripts/` observability data: function entries get empty channels and
  side-effect weight 0.

## Accepted Examples

- A simple uncovered function with no coverage artifact emits
  `coverage_state: unknown`, `crap_score: null`, and a fallback risk band.
- A complex function with 50% measured coverage emits `coverage_state: known`
  and a CRAP score from the documented formula.
- A `scripts/` function that writes a ledger-like file receives
  `ledger_or_protocol_write_candidate` and side-effect weight 4.
- A complex formatter in `src/wea_cli` can rank below a similarly complex
  GitHub/ledger-facing `scripts/` function because side-effect weight changes
  review priority.

## Rejected Examples

- Treating absent coverage as 0% coverage is rejected because it invents a
  denominator.
- Treating absent coverage as 100% coverage is rejected because it hides risk.
- Reporting only file-level line counts or complexity totals is rejected because
  review needs function-level evidence.
- Claiming high CRAP automatically rejects a PR is rejected because Circle-1
  metrics are advisory.
- Hiding skipped nested files or parse errors is rejected because it moves the
  denominator.

## Pre-Implementation Spec Redteam

1. The issue could be gamed by producing only a prose CRAP policy. Fix: the
   deliverable includes a runnable script and tests.
2. The issue could be gamed by silently assuming missing coverage is zero. Fix:
   unknown coverage is a first-class state and CRAP stays null.
3. The issue could be gamed by listing only files. Fix: entries are function and
   method level with symbols and line spans.
4. Observability could be over-joined at file level. Fix: channel evidence is
   filtered to lines within the function span.
5. The checkpoint could become noisy. Fix: CLI supports compact JSON truncation
   with omitted-count disclosure.

## Pre-Implementation Logic Redteam

1. AST complexity is approximate and can miss semantic risk. It is documented as
   `python_ast_cyclomatic_v0`, not as proof of correctness.
2. Line coverage does not prove branch coverage. The harness ingests line
   coverage only and keeps the source visible.
3. Coverage XML and JSON disagree on shape. The reader normalizes both into
   executed and missing line sets.
4. Observability line evidence can miss wrapper calls. The existing #884
   scanner already documents this limitation; the CRAP harness inherits it.
5. Compact checkpoints can omit lower-risk functions. The omitted count is
   explicit, and Agent0 can rerun without `--max-json-functions`.

## Implementation Self-Roast

Specific possible flaws:

1. Complexity scoring might undercount Python constructs not represented in the
   v0 visitor, especially newer syntax.
2. Function coverage based on line spans may include decorators or docstrings
   differently from a future coverage.py function-level artifact.
3. Observability annotation is line-local, so a helper that calls a risky helper
   in the same file may look quiet.

Missed edge cases:

1. Coverage JSON produced by a future coverage.py version may have function
   sections that this v0 reader ignores.
2. A parse-error file with no functions is surfaced in summary but not as a
   pseudo-function risk item.

Fixes made or status:

1. Fixed the biggest honesty risk by requiring `coverage_unknown` when no
   explicit artifact is supplied.
2. Fixed file-level observability overreach by filtering detection evidence to
   the function span.
3. Could not prove semantic call-graph side effects without executing or doing
   interprocedural analysis; left it as an explicit limitation.

## Post-Implementation Redteam And Fix Notes

- Redteam: compact JSON might make `summary.functions` equal only the truncated
  count. Fix: summary is computed from all discovered functions before
  truncation.
- Redteam: `scripts/__init__.py` could disappear because the observability
  scanner excludes it by default. Fix: the CRAP harness calls observability with
  `include_init=True`.
- Redteam: unsupported coverage files could quietly produce unknown coverage.
  Fix: unsupported extensions and malformed artifacts are CLI errors.

## Final Codex Review Notes

- In scope: new harness, logic note, compact pilot checkpoint, and focused tests.
- Out of scope preserved: no ledger mutation, no Tide change, no CI gate, no
  GitHub workflow or issue-template change.
- Review usefulness: the top-risk report shows which current functions combine
  complexity, unknown/known coverage, and observable side-effect surfaces, so
  Agent0 can inspect risky code paths before relying on subjective simplicity
  claims.
