# Circle-1 CRAP pilot tracking — 2026-05-02

This is the pilot tracking note for issue #888. It frames how the
`crap_inventory.py` baseline checkpoint is read by future Circle-1 sweeps.

## Baseline

- harness: `scripts/circle1/crap_inventory.py` v1
- baseline JSON: `domains/circle-1/checkpoints/crap--2026-05-02.json`
- baseline markdown (top-25): `domains/circle-1/checkpoints/crap--2026-05-02.md`
- pilot scope: `scripts/**/*.py` and `src/wea_cli/**/*.py`
- coverage artifact at baseline: **none** — every function carries
  `coverage_state=unknown`. CRAP scores are deliberately not computed.
  Risk bands are derived from complexity + side-effect weight.
- function count at baseline: see baseline JSON `summary.function_count`.

## Why no coverage artifact at baseline

Issue #888 explicitly admits this case: "report `coverage_unknown` when no
coverage artifact is supplied". Producing a real coverage.py JSON would
require running `coverage run` against the full pytest suite, which has
known unrelated baseline failures and is out of scope for this PR. A later
Circle-1 sweep can re-run the harness with `--coverage` once a stable
coverage artifact exists, and the JSON shape will not change.

## How to read the baseline

The top-risk list in the markdown report identifies the functions most
likely to repay reviewer attention **today**, even without coverage data:

- `risk_band = unknown_high` with `side_effect_weight = 4` is the loudest
  category — high cyclomatic complexity in files that touch ledger or
  GitHub. These are the functions where a bug compounds across systems.
- `risk_band = unknown_high` with weight 0..2 is still high-complexity
  code, but the consequence is more local (e.g. a 30-branch report
  formatter).
- `risk_band = unknown_low` is **not** a clean bill of health when
  coverage is unknown; it means the function is short. A reviewer should
  still check it if it sits next to a high-band function.

## Tracking protocol

`tracking_status` for every record begins at `new`. Future sweeps update
the status with explicit evidence:

- `watched` — the function appeared in the top-N list of the previous
  Circle-1 sweep and reviewers chose to keep an eye on it. Requires
  `evidence_refs` with at least one prior checkpoint path.
- `correlated` — a later PR review finding, redteam note, bug fix, or
  hardening task touched this function. Requires
  `evidence_refs` with the PR/issue/note pointer.
- `retired` — the function was removed, renamed, or split such that the
  baseline pointer no longer applies. Requires `evidence_refs` with the
  removing commit hash.
- `inconclusive` — the inspection window closed without any of the above.
  Allowed; required by the issue's MUST NOT rule against rewriting
  settlement by inspection alone.

The harness itself never promotes status. Promotions happen in a
sidecar tracking file under `domains/circle-1/checkpoints/` (e.g.
`crap--2026-05-02--tracking.jsonl`), which is created when the first
follow-up sweep runs. The sidecar format is one JSON object per line with
fields `path`, `symbol`, `start_line`, `tracking_status`, `evidence_refs`,
and `tracking_notes`. The harness will be extended to consume the sidecar
in v2; for v1 the sidecar is read by humans.

## Inspection window for #888

- next Circle-1 checkpoint after merge
- the next five accepted Python code-change tasks touching `scripts/` or
  `src/wea_cli/`

For each accepted task in that window, Agent0 runs the harness on the
post-merge commit, diffs against this baseline, and writes one tracking
sidecar entry per touched function:

- if the touched function appears in the previous top-N: write
  `correlated` and the PR number;
- if the touched function is a new high-band function: write `watched`
  and the PR number;
- if the touched function dropped out of the top-N because complexity
  fell or coverage was added: write `retired` and the commit hash.

If the window closes with zero touched functions in the top-N, the entire
baseline is recorded as `inconclusive` for this cycle. Per the issue's
inconclusive policy, that is a legitimate outcome — not a failure of the
harness.

## What the baseline already tells reviewers

A spot check against the live repo shows that at the top of the
`unknown_high` list sit `scripts/process_pending.py::process`,
`scripts/check_task_format.py::validate_detailed`, and several
`TideProcessor._task_create` / `_accept` / `_ranking` methods. These
functions combine cyclomatic complexity ≥ 30 with side-effect weight 4
(ledger writes + GitHub side-effects). A reviewer reading the report
should:

- prefer to make any non-trivial change to those functions through a
  staged refactor PR rather than a one-shot edit;
- ask explicitly for branch coverage on those functions before approving
  a change that adds new branches;
- flag any added subprocess invocation in those files as needing a
  manual sandbox check.

That last paragraph is the immediate "review usefulness" claim required
by the issue: the report does change at least one current review
decision, which is "approve a 200-line edit to `tide.py::_accept`
without asking for tests or branch coverage". After this baseline,
the answer to that decision is "no, ask for coverage first".

## Out of scope for this pilot

- No CI gate is introduced; the harness is advisory.
- No Tide settlement rule is introduced.
- No issue template or .github workflow is changed.
- No ledger data is touched.
- The full per-function JSON is regenerable; only the top-30 checkpoint
  is committed.
- Branch-coverage support, LCOV/XML support, function-scoped
  observability annotation, and decorator complexity are documented v2
  follow-ups, not v1 deliverables.
