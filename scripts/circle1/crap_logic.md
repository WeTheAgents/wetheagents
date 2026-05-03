# Circle-1 CRAP risk harness logic

This is the code-free architecture note for `crap_inventory.py`. It exists so
reviewers can audit the harness's reasoning without reading Python.

## Why this harness exists

Code review burden in WeTheAgents has been intuition-led: a reviewer reads a
diff and decides "this looks simple". CRAP (Change Risk Anti-Patterns) gives
that intuition a numeric form. It says: "complex code without coverage is
riskier than simple or well-covered code", with a formula
`crap = complexity^2 * (1 - coverage)^3 + complexity` that grows fast when
either input gets bad and collapses to plain complexity at full coverage.

CRAP alone is too narrow for WEA. A `scripts/` function that runs `gh issue
comment` is more interesting than a `scripts/` function that pretty-prints a
table, even at the same complexity. Issue #884 already wrote an observability
inventory for `scripts/`. This harness joins the two: function-level
complexity and coverage on one side, observability channels on the other,
attributed to functions by intersecting each detection's evidence line
numbers with the function's source span.

## Actors

- **harness**: reads source files and an optional coverage artifact, never
  imports or executes scanned code, never calls GitHub or the ledger.
- **observability_inventory**: invoked in-process to enrich `scripts/`
  results. Allowed to be missing, errored, or empty without breaking the
  harness.
- **reviewer (Agent0 or another agent)**: reads the JSON or markdown output
  and decides where to focus review attention.

## Inputs

- `root` — repo root.
- `includes` — by default `scripts` and `src/wea_cli`. Other directories can
  be passed but `src/wea_cli` and `scripts` are the only zones the v1 risk
  semantics were tuned for.
- `coverage` — optional path to a coverage.py-shaped JSON artifact.
- `scan_date` — optional ISO date for reproducible reports.

## Per-function record fields

Each emitted record carries the fields suggested by the issue plus a small
number of harness-specific additions:

- `path`, `symbol`, `start_line`, `end_line` — function location.
- `complexity` — integer cyclomatic complexity per the documented formula.
- `complexity_source` — the formula description, repeated on every record so
  later checkpoints survive harness changes.
- `coverage_state` — one of `known`, `unknown`, `not_applicable`.
- `coverage_percent` — fraction in `[0, 1]` when state is `known`, else null.
- `crap_score` — float when both complexity and coverage are known, else
  null. Never invented.
- `risk_band` — one of `low`, `medium`, `high` (when coverage is known) or
  `unknown_low`, `unknown_medium`, `unknown_high` (when coverage is unknown
  or not applicable).
- `risk_reason` — short string explaining the band.
- `observability_channels` — sorted list of detected channel names, or
  empty for zones where the inventory does not apply.
- `observability_state` — `joined`, `missing`, or `not_applicable`.
- `side_effect_weight` — integer derived from the worst-channel rule below.
- `tracking_status` — always `new` from this harness; future sweeps may
  update via sidecar evidence.
- `tracking_notes`, `evidence_refs`, `notes` — free-form fields reserved for
  later annotation passes; the harness leaves them empty.

## Scoring states

### Coverage state

- `known` — a coverage artifact was supplied and at least one executable line
  in the function range appears in the artifact's `executed_lines` or
  `missing_lines`.
- `unknown` — no coverage artifact was supplied, or the artifact does not
  mention this file.
- `not_applicable` — the function range contains no executable lines per the
  coverage artifact (e.g. all-docstring stub).

### CRAP score

CRAP is computed only when `coverage_state == known`. In every other case
`crap_score` is null. This is the harness's hard line against the
"missing-coverage = full coverage" gaming pattern called out in #888.

### Risk band

- `coverage_state == known`:
  - `crap >= 30` -> `high`
  - `5 <= crap < 30` -> `medium`
  - `crap < 5` -> `low`
- otherwise (unknown or not_applicable):
  - base by complexity: `>=10` -> `unknown_high`, `>=5` -> `unknown_medium`,
    else `unknown_low`
  - if `side_effect_weight >= 3` and base is `unknown_medium`, escalate to
    `unknown_high`
  - if `side_effect_weight >= 3` and base is `unknown_low` with complexity
    `>= 3`, escalate to `unknown_medium`

The escalation rule encodes the principle that an unobserved side-effecting
function deserves more reviewer attention than an unobserved pure helper.

### Side-effect weight

Derived from observability channels using the worst-channel rule:

| channel | weight |
|---|---:|
| `ledger_or_protocol_write_candidate` | 4 |
| `github_comment_side_effect_candidate` | 4 |
| `subprocess_launch` | 3 |
| `network_external_call` | 3 |
| `file_artifact_write` | 2 |
| `unknown_ambiguous_side_effect` | 2 |
| `logging` | 1 |
| `stdout_cli_output` | 1 |
| `stderr_output` | 1 |

`weight = max(weight(c) for c in detected_channels)`, or 0 when no channels
are detected. Channels are attributed **per function**: the harness
intersects each observability detection's evidence line numbers with the
function's source span, so a pure helper does not inherit the side-effect
channels of neighbouring functions in the same file. Detections without
evidence line numbers cannot be bound to a function and are recorded as a
limitation (see below) rather than fanned out file-wide.

## Invariants

- The harness never mutates the ledger, calls GitHub, runs subprocesses, or
  imports scanned code.
- `crap_score` is non-null **iff** `coverage_state == "known"`.
- `coverage_state` is one of three explicit strings; "missing artifact" and
  "covered" are never collapsed.
- Two runs against the same commit with the same arguments produce
  byte-identical JSON output (`sort_keys=True`, sorted collections, rounded
  floats, no wall-clock embedding inside per-function records).
- `tracking_status` is always `new` when emitted by this harness; promotion
  requires explicit evidence on a later run.
- Skipped files and file problems are reported, never silently dropped.

## Failure paths

- **Missing coverage artifact path**: CLI returns exit 1 before scanning.
- **Malformed coverage artifact**: raised as `ValueError`; the harness does
  not silently fall back to `unknown` because that would hide reviewer
  intent (they meant to supply a real artifact and got it wrong).
- **Unreadable source file**: recorded in `file_problems` with status
  `read_error`; no functions emitted for that file.
- **SyntaxError in source file**: recorded in `file_problems` with status
  `parse_error`; no functions emitted for that file.
- **Observability inventory missing or erroring**: harness still runs;
  every `scripts/` file emits `observability_state=missing` and an empty
  channel list. Reviewers see the missing annotation; they don't see a
  silently zero side-effect weight presented as evidence of safety.
- **Empty function file (only imports/docstrings)**: file appears in
  `file_problems` with status `no_functions`, no functions emitted.

## Accepted examples

- A 2-branch `scripts/` function with no observability channels and no
  coverage gets `risk_band = unknown_low`, `crap_score = null`, weight 0.
- The same function with 80% coverage gets `risk_band = low`,
  `crap_score = ~ 1.4`.
- A 12-branch `scripts/` function whose file contains a `gh` subprocess
  call and no coverage gets `risk_band = unknown_high`, weight 3.
- A function entirely contained in a class method's body inside a nested
  class is discovered with the qualified name `Outer.Inner.method`.
- A function spanning lines 10..40 with `executed_lines = {10, 12, 14}`
  and `missing_lines = {20, 30, 40}` reports `coverage_percent = 0.5`
  (3/6 executable lines hit).

## Rejected outcomes

- A report that lists files but not functions does not satisfy this logic.
- A report that emits a numeric `crap_score` when no coverage artifact was
  supplied does not satisfy this logic.
- A report that promotes `tracking_status` to `correlated` without an
  evidence_ref does not satisfy this logic.
- A report that hides nested files in `scripts/` or `src/wea_cli/` from the
  scan or the skipped list does not satisfy this logic.
- A report that uses observability "no channels detected" as evidence the
  function is safe does not satisfy this logic — the inventory is AST-only
  and has documented limits.

## Known v1 limitations (carried forward to logic)

- Observability detections that carry no evidence line number cannot be
  attributed to a specific function. The harness ignores them when binding
  channels to functions and surfaces this fact in the report's top-level
  `limitations` list, rather than fanning the detection out file-wide. The
  effect is that pure helpers in side-effecting files do not inherit a
  side-effect weight they did not earn; the trade-off is that an
  evidence-less detection is invisible at function granularity until the
  observability inventory grows line-level evidence for that channel.
- Decorators are not folded into a function's complexity.
- `match` case `if` guards are not counted as additional decision points.
- Branch coverage data, if present in the coverage artifact, is ignored;
  only line coverage is consumed.
- `src/wea_cli` files always carry `observability_state = not_applicable`
  until a `wea_cli` inventory exists.
- v1 ingests only coverage.py JSON. XML and LCOV are documented future work.
