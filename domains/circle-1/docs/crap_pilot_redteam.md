# CRAP risk harness — pre-implementation redteam (issue #888)

This note is written before the harness is built. It is paired with the
post-implementation redteam in the same file (lower section) so reviewers can
see whether the predicted holes were closed or just acknowledged.

## Spec redteam (against issue #888)

These are challenges to the issue text, not the implementation.

1. **CRAP is a known-noisy metric.** The classical formula
   `crap = complexity^2 * (1 - coverage)^3 + complexity`
   produces large numbers for high complexity even at near-100% coverage.
   It also collapses to `complexity` when coverage = 1.0, which means the
   harness must never silently treat unknown coverage as 1.0; that would be
   indistinguishable from "covered". The spec's "report `coverage_unknown`
   when no artifact is supplied" rule directly addresses this. The harness
   must enforce three branches: `known`, `unknown`, `not_applicable`, and
   refuse to compute `crap_score` outside `known`.
2. **Cyclomatic complexity is not the same as risk.** A 30-branch dispatcher
   with no side effects is less risky than a 4-branch ledger writer. The
   spec mitigates this by requiring observability annotation, but the spec
   does not bind the two together. Decision: `risk_band` must blend
   coverage-state, complexity, and side-effect weight; pure CRAP rank alone
   is not a risk band.
3. **"Top risk" is implicitly a ranking.** Without a stable tie-breaker the
   ranking will jitter across runs and pollute checkpoint diffs. Decision:
   final sort key is `(risk_band_tier desc, side_effect_weight desc,
   crap_score desc with unknown coerced to a deterministic ceiling for
   ranking only, complexity desc, path asc, start_line asc)`. The
   ranking-only ceiling MUST NOT leak into the JSON `crap_score` field.
4. **Observability inventory ships v0 limitations.** It is AST-only and
   misses wrappers and dataflow. The harness must NOT upgrade those
   limitations by claiming a function "has no side effects" — it can only
   say "no detectable side-effect channels in scripts/ inventory at this
   commit". Decision: `side_effect_weight` for src/wea_cli is
   `not_applicable` until Circle-1 grows a wea_cli inventory.
5. **Coverage artifacts are platform-shaped.** `coverage.py` JSON is the
   most likely artifact; XML and LCOV exist too. v1 ingests coverage.py
   JSON only and emits an explicit `coverage_artifact_format` field so a
   later v1.1 can add formats without rewriting consumers.
6. **Issue scope creep risk.** Reward dropped from 120 to 40 WEA. The harness
   must avoid expanding into a generic Python audit tool. Decision: stay
   within `scripts/**/*.py` and `src/wea_cli/**/*.py`; emit a clean
   exclusion record for nested files we deliberately skip (none expected
   today, but reserve the field).

## Logic redteam (against the design before implementation)

These are challenges to the design itself.

1. **Complexity counting is judgment-laden.** Different references count
   `BoolOp`, `IfExp`, `comprehensions with if`, `match cases`, and `assert`
   differently. Decision: count
   `If, For, AsyncFor, While, ExceptHandler, With items > 1, AsyncWith,
   IfExp, BoolOp operand-1, comprehension if clauses, match.cases - 1,
   assert` once each; document the choice in `complexity_source` and in
   `crap_logic.md`. We document the choice rather than chase a "correct"
   industry standard, because reviewers compare runs of the same harness.
2. **Coverage at function granularity is fuzzy.** coverage.py reports lines,
   not functions. A function spanning lines 10..40 with executed_lines
   touching 10, 12, 14 is partially covered, not fully or zero. Decision:
   coverage_percent = `executed_in_range / executable_in_range`, where
   executable_in_range = `len(set(executed_lines) | set(missing_lines)) ∩
   range(start_line, end_line+1)`. If executable_in_range is empty (e.g.
   pure docstring/import block), coverage_state = `not_applicable` and
   crap is not computed.
3. **Honest unknown handling has its own gaming surface.** A submission
   that runs without `--coverage` and then claims "Circle-1 review wants
   coverage_unknown" is gameable. Decision: the harness records, in the
   header, whether a coverage artifact was provided. If not, the markdown
   top-risk report opens with a single sentence: "No coverage artifact
   supplied; CRAP scores were not computed; risk bands fall back to
   complexity + side-effect weight." Reviewers cannot miss it.
4. **Joining inventories invites schema drift.** If `observability_inventory.py`
   v0 changes shape (e.g. renames a channel), this harness can either crash
   or silently drop the annotation. Decision: tolerate missing channels
   (annotation is best-effort) and pin the channel-name set to whatever
   inventory currently exposes via `CHANNELS`; never hard-code names.
5. **Determinism is the silent acceptance criterion.** Two runs on the same
   commit must produce byte-identical JSON. Decision: sort all collections,
   stringify floats with a fixed format (`round(x, 4)`), and avoid `set`
   ordering at output time.
6. **Tracking semantics must NOT auto-promote.** The spec lists
   `new / watched / correlated / retired / inconclusive`. The harness must
   only ever emit `new` or carry a value forward from an explicit input.
   Auto-correlation would let later sweeps "prove" usefulness without
   evidence. Decision: tracking_status defaults to `new`; future sweeps
   must update by reading evidence and writing a sidecar tracking file.
7. **Test brittleness.** Tests written against absolute paths or full
   inventory output will break when scripts/ grows. Decision: tests
   construct a temp repo with synthetic scripts/ and src/wea_cli/ trees
   and assert on shape, not on counts of the live repo.

## Implementation self-roast

Filled in after the implementation lands. See `crap_pilot_2026-05-02.md` for
the baseline + tracking note that this redteam plan was used to build.

### Three specific possible flaws

1. **Complexity counting under-counts `match` cases.** I count
   `len(node.cases) - 1` rather than including guards. A `match` with
   guards under-reports decision points relative to a chain of `if/elif`.
   Mitigation: documented in `crap_logic.md`. Not fixed in v1; a follow-up
   could add `+1 per case guard` once we have pilot evidence that match is
   used in scripts/ in a way that matters.
2. **Coverage at branch granularity is not modeled.** coverage.py supports
   branch coverage; this harness only consumes line coverage. A function
   with 100% line coverage but skipped branches will appear safe.
   Mitigation: documented; ingest is forward-compatible — if `branches`
   appears in the JSON for a file, we ignore it cleanly rather than crash.
3. **Observability annotation must be function-level, not file-level.**
   An earlier draft inherited a file's worst channel onto every function
   in that file, which over-flagged pure helpers in side-effecting files.
   Fix: the final harness intersects each observability detection's
   evidence line numbers with each function's `[start_line, end_line]`
   span, so a pure helper does not pick up a neighbouring function's
   side-effect channels. The remaining real limitation is narrower:
   detections that carry no evidence line number cannot be attributed to
   a specific function and are surfaced in the report's top-level
   `limitations` list rather than fanned out file-wide. That trade keeps
   the false-positive shape (over-flagging) out of the output at the
   cost of an evidence-less detection being invisible at function
   granularity until the inventory grows line-level evidence for that
   channel.

### Two missed edge cases (could not fully prove fixed)

1. **Decorators with side-effecting calls.** A function decorated with
   `@click.command()` is a Call expression at module load, not inside the
   function body. The current harness skips decorators when computing
   complexity for the function body. Decorators with conditional logic
   are rare in scripts/ but exist (e.g. `@functools.lru_cache(maxsize=...)`
   with computed argument). I did not test this branch and could not
   prove the harness behaves well. Mitigation: documented in
   `crap_logic.md` as a known limitation; risk is small in this corpus.
2. **Generated or stub files.** A future autogen step could emit Python
   under `scripts/`. The harness scans them. They might have very low
   complexity but high observability surface (e.g. a generated subprocess
   wrapper). The pilot tracking baseline would mark them `new` and a
   reviewer could plausibly think they need review. I did not introduce a
   per-file ignore mechanism; the spec's MUST NOT rule against silent
   exclusion is a stronger constraint than the cost. The exclusion list
   is therefore empty by default, and any future skip must be reported.

## Post-implementation redteam (after coding)

1. **Determinism.** Two consecutive runs against the live repo produced
   byte-identical JSON. Verified by `diff` on two outputs. The harness
   does not embed wall-clock time inside any per-function record; only
   the top-level `scan_date` is date-stamped, and that field is
   overridable for reproducible builds (`--scan-date`).
2. **Coverage-unknown banner.** When called without `--coverage`, the
   markdown report opens with the unknown-coverage banner; the JSON
   header carries `"coverage_artifact": null`. A submission that hides
   this would have to actively delete the banner, which is visible in
   review.
3. **Side-effect weight gameability.** `weight` is derived from the
   observability inventory, which the harness re-runs. A reviewer can
   reproduce both numbers from source. There is no place to silently
   widen a low-side-effect function's weight without changing
   `observability_inventory.py`, which is itself reviewed.
4. **Schema stability.** Field names match the suggested-fields list in
   the issue. New fields were added (`exclusion_reason`, `notes`,
   `complexity_source`, `coverage_artifact_format`,
   `harness_version`) and are documented in `crap_logic.md`. Removing
   any of them in a later release would be a breaking change and must
   bump `harness_version`.

## Final review notes (for Agent0 acceptance)

- Coverage MUST line: satisfied — `--coverage` ingest plus
  `coverage_unknown` fallback are tested explicitly.
- "Honest fallback risk band when coverage is unknown" MUST line:
  satisfied — band tiers `unknown_low / unknown_medium / unknown_high`
  are derived from complexity and side-effect weight, never silently
  promoted to a CRAP-derived band.
- "Annotate or join #884 observability channels for `scripts/`" MUST
  line: satisfied — `scripts/` functions are annotated with the
  observability channels whose evidence lines fall inside the function
  span, via `observability_inventory.scan_observability`. `src/wea_cli/`
  files explicitly emit `observability_state: not_applicable`. The
  inventory is allowed to be missing or empty without breaking the
  harness.
- "Compact baseline/checkpoint" MUST: satisfied — checkpoint commits
  the top-30 risk items only; the full JSON is regenerable but is
  intentionally not committed.
- "Tests cover complexity scoring, coverage-known and coverage-unknown
  states, CRAP calculation, observability annotation, and stable
  output shape" MUST: satisfied — `tests/test_crap_inventory.py` has
  one test per bullet plus a determinism test.
- MUST NOT rules: no CI, no Tide, no ledger, no .github changes, no
  rewrite of `scripts/` or `src/wea_cli/`, no claim of usefulness
  without evidence (the markdown header explicitly says "tracking is
  inconclusive until at least one watched function is touched").
