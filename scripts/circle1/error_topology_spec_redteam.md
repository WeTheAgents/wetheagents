# Error topology census — pre-implementation redteam

This is the redteam pass run against `error_topology_logic.md` **before** any
code is written. It splits into two halves: spec redteam (asks whether the
contract itself is well-shaped) and logic redteam (asks whether the algorithm
delivers what the contract promises).

The goal is to attack the design before reviewers do, and to record the
trade-offs so the post-implementation pass can verify each one.

## Spec redteam

### S1. Does the census actually answer the issue's question?

**Attack.** Issue #885 asks for a *repo-wide* topology view, with `src/wea_cli`
as a pilot. A scanner that defaults to `src/wea_cli` plus `scripts/` may still
look like "two zones rebadged as repo-wide".

**Defense.** The default zones cover the only first-party Python zones in WEA
(`src/wea_cli` and `scripts/`). The CLI accepts `--zones` to widen scope so
future Python zones (`domains/<name>/`, `gunnery/`) can be folded in without a
code change. The `score_inputs` and `by_zone` shapes are zone-agnostic. A
zone called `other` exists for arbitrary additions.

**Residual risk.** "Repo-wide" is still a configurable claim. The pilot
analysis names this explicitly in its scope section.

### S2. Is `src/wea_cli` the right pilot, or just the pretty one?

**Attack.** `src/wea_cli` is small (20 files) compared to `scripts/` (149+
files). A pilot that picks the small zone may be hiding from the hard one.

**Defense.** `src/wea_cli` is the user-visible CLI boundary; it is also the
zone where errors are most directly converted into agent-visible failures
(exit codes, printed messages, GitHub PR errors). `scripts/` is internally
oriented and runs under CI/Tide. The pilot picks the boundary that most
benefits from a typed error contract; it does not avoid `scripts/`.

**Residual risk.** The pilot recommendation must not be applicable only to
`src/wea_cli`. The post-impl note must say what the next zone hardening
candidate is.

### S3. Does the score rubric admit cosmetic wins?

**Attack.** The v0 rubric goes from `1` (scattered) to `2` (shared base in a
zone) to `3` (repo base with documentation). An agent could mint a base class
called `WeaError`, have one existing class inherit from it, and call it `2`.

**Defense.** The harness only counts a zone as `2` when at least **two**
classes share a base, AND that base is itself one of the detected custom
exception classes. The `padded_hierarchy` flag fires when a base has zero
real raises in the scanned tree, so a paper-only base does not move the
score.

**Residual risk.** The first-mover penalty: a zone with one existing custom
class plus a fresh base now needs at least one more subclass to score `2`.
This is intentional. It prevents a single subclass from inflating the score.

### S4. Score `4` requires enforcement — what counts?

**Attack.** "Enforcement" is fuzzy. A test that imports the base class is not
the same as a CI gate that rejects PRs without a base class.

**Defense.** `enforced_check` is operator-supplied via `--enforced-check`, not
auto-detected. The flag accepts a path to a checker that the operator
declares relevant. The harness never claims `4` on its own.

**Residual risk.** This means score `4` is unreachable from the harness alone.
That is acceptable for v0; v1 can add a small registry of accepted check
patterns.

### S5. What about the test directory?

**Attack.** Excluding `tests/` from the default scope hides
`TestMalformedJsonError` and similar classes that *do* live in the repo.

**Defense.** `tests/` is included on demand via `--zones`. The default scope
exclusion is reported in `skipped_files`-shape metadata under
`scope.default_exclusions` and called out in the JSON output. The pilot
analysis explains why test errors are different from production errors.

**Residual risk.** A reviewer who runs the harness without reading the docs
may misread the headline number. The CLI prints a one-line scope reminder on
stderr when zones are at defaults.

### S6. Will the JSON shape change between checkpoints?

**Attack.** If the JSON shape evolves, comparing two checkpoints becomes a
manual diff exercise.

**Defense.** The output carries `harness_version: "v0"`. Schema changes bump
the version. The summary keys are flat enough that older consumers will
still see counts they recognize.

**Residual risk.** v0→v1 will require operator effort. Acceptable; documented.

## Logic redteam

### L1. Inheritance graph is name-based — false matches?

**Attack.** Two unrelated classes both named `Error` in different files would
collide in the name-based graph.

**Defense.** Class names are tracked with their declaring path, so the report
distinguishes `wea_cli.gh.Error` from `scripts.x.Error`. The `inheritance`
dict uses bare names because the rubric only asks "is there a shared base
inside the zone", which is name-resolvable enough.

**Residual risk.** Cross-zone false matches still possible. The pilot
analysis names this and documents it as a `v1` upgrade.

### L2. Dynamic class generation

**Attack.** Code that builds an exception class via `type(...)` or
`typing.NewType(...)` is invisible to the AST scanner.

**Defense.** This is acknowledged as a limitation in the JSON `limitations`
list. WEA does not currently use dynamic class generation in the scanned
zones; if it appears later, the harness will silently undercount, which is
the safer failure mode (false negative beats false positive on
`exception_topology_score`).

**Residual risk.** A future zone using metaclasses would need a v1 upgrade.

### L3. Re-raise chain detection is brittle

**Attack.** `try: ...; except H as e: ...; raise X(...)` is a wrap pattern,
but `try: ...; except H: ...; raise X(...)` (no `as`) is the same pattern in
spirit. Code that re-raises after rebinding `e` to a different name might be
missed.

**Defense.** The harness records the wrap pattern when an `except` handler
contains a `raise X(...)` call (with or without `from`). It records the
inner exception type from the handler's `type` clause and the outer type
from the `raise X(...)` call. If `from` is missing, the detection still
fires but is annotated with `from_clause: false` so post-hoc reviewers can
filter. This is more permissive than a strict matcher but matches the
spirit of "wrap or re-raise".

**Residual risk.** Some recorded `reraise_chain` events are not wraps but
fall-through patterns. They are documented as such in the JSON.

### L4. CLI / GitHub failure surface heuristics

**Attack.** The "file looks like a CLI" heuristic is fuzzy: a script with a
single `def main()` may not actually be a CLI surface.

**Defense.** The flag is annotation-only. It does not change the topology
score. It is reported so reviewers can read the headline number with the
right lens.

**Residual risk.** The flag may produce false positives. Acceptable because
it is informational.

### L5. Built-in raise list might miss something

**Attack.** The list of "built-in" classes is hand-rolled and might miss
`UnicodeDecodeError`, `IndexError`, etc.

**Defense.** The list covers the common `wea_cli`/`scripts` failure modes
seen during the pre-impl scan. The `raw_builtin_raise_at_boundary` detection
falls back to a name-suffix check for any name in the Python builtins
namespace ending in `Error` or `Exception`. The list is documented in the
JSON `kinds` section so reviewers can see what was treated as a built-in.

**Residual risk.** Edge cases like `_csv.Error` exist; they are not in the
built-in namespace but feel built-in. They are detected as `custom_raise`
with confidence `low`, which is the closest honest match.

### L6. Stable summary across checkpoints

**Attack.** A diff between two checkpoints will be noisy if line numbers
change for unrelated reasons.

**Defense.** The summary section (counts, scores) is line-number-free. The
per-file detection lists carry line numbers but are sorted deterministically.
Diff consumers should diff `summary` and `score_inputs` first, and only drop
into `files` when a count moved.

**Residual risk.** A pure refactor that moves classes around will produce a
big `files` diff with no semantic change. Acceptable; documented in the
header comment of the harness.

## Decisions made before coding

1. The default scope is `src/wea_cli/**/*.py` and `scripts/**/*.py`.
2. `tests/` is opt-in via `--zones`.
3. The score rubric is computed per zone, with the repo aggregate equal to
   the minimum non-empty zone score.
4. `enforced_check` is operator-supplied; the harness never auto-claims `4`.
5. JSON is the canonical output. Markdown is a human-friendly summary
   produced from the same JSON.
6. The harness does not import scanned modules. It is AST-only.
7. The pilot will recommend (but not bundle) a `WeaCliError(RuntimeError)`
   base in `src/wea_cli/errors.py`, with the three existing custom errors
   inheriting from it. Whether to bundle the change in this PR or leave it
   for a follow-up Gauntlet `T4` slot is a decision that lives in
   `error_topology_pilot.md`, not in the census harness.
