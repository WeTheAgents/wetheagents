# Error topology census — post-implementation redteam

This is the redteam pass run **after** the harness, the H1 pilot change
(`src/wea_cli/errors.py` + three subclass edits), the tests, and the two
checkpoint artifacts landed. It cross-checks every claim from the pre-impl
spec/logic redteam and records the bugs the implementation phase exposed.

## Bugs found during implementation and fixed

The implementation phase plus codex review iteration uncovered fourteen
real correctness issues. Each is logged below with its symptom, cause, fix,
and the regression test that locks the fix in. The harness now passes the
full codex review with no discrete, actionable correctness findings.

### B1. Repo-shared bases included built-in classes

**Symptom.** First live run reported
`repo_shared_bases: ['RuntimeError']` for both zones, because most custom
errors subclass `RuntimeError` directly.

**Why it matters.** A future zone that scored `2` could trip into `3`
without a real cross-zone hierarchy, just because Python built-ins are
universal.

**Fix.** `_zone_score_inputs` now filters `repo_base_to_zones` to only count
bases that are themselves declared as a custom exception class somewhere in
the scan. Built-ins like `RuntimeError`, `ValueError`, `Exception` are
excluded by construction.

**Verified by.** `test_score_never_four_without_enforced_check` exercises
the cross-zone path explicitly. Live `with-h1.json` reports
`repo_shared_bases: []` for both zones, as expected (no cross-zone custom
base yet — that is exactly the current state).

### B2. Class detection missed names without Error/Exception suffix

**Symptom.** Test `test_custom_exception_class_detected` asserted that
`class ChildFail(BaseFail)` was detected as a custom exception class. The
single-pass heuristic only checked the class name's suffix and the
*direct* base names' suffix; it did not follow inheritance chains.

**Fix.** Added a true two-pass scan. Pass 1 collects every class
declaration; `_expand_exception_like_names` builds the global set by
fixed-point iteration (a class joins the set if any base is already in
the set or is a built-in exception). Pass 2 visits each file with the
known set available, so `class ChildFail(BaseFail)` is now detected even
though the suffix says `Fail`, and `raise ChildFail()` is now classified
as `custom_raise` even though `ChildFail` doesn't end in `Error`.

**Verified by.** All score-rubric tests pass. The live live `cli.py`
detection count is unchanged because every WEA custom error already uses
the `Error` suffix.

### B3. Double-visit of `try` body via `generic_visit`

**Symptom.** A `raise GhError(...) from e` inside an `except` handler
produced **two** `custom_raise` detections — one with `in_handler: True`
and one with `in_handler: False`. The first run reported
`custom_raise: 99 detections`. After the fix the same scan reports
`79 detections`, an over-count of ~25%.

**Root cause.** `visit_Try` walked handlers manually (to keep the
handler-type stack accurate) and then called `self.generic_visit(node)`,
which re-descended into the same handlers via the default fallback. Every
node inside a handler body got visited twice; the second visit had an
empty handler stack so it lost the `in_handler` annotation.

**Fix.** `visit_Try` now walks `body`, `orelse`, and `finalbody` directly
and never calls `generic_visit`. The handlers are walked once, with stack;
non-handler children are walked once, without stack.

**Verified by.** `test_no_double_count_inside_try_body` is a regression
test that fails on the old code and passes on the new code.

**Side effect.** The `broad_catch` count also dropped from 27 → 24 because
nested `try/except` patterns inside an outer handler were doubling. This
is a *correction*, not a degradation; the lower number is the truth.

### B4. `repo_shared_bases` was computed globally, not per-zone

**Symptom.** Codex test: zones B and C share a base `RBase`; unrelated
zone A's `repo_shared_bases` was populated with `RBase`, inflating zone
A's score from 2 to 3.

**Fix.** `_zone_score_inputs` now restricts `repo_shared_bases` to bases
where `zone in zone_set`. Test: `test_repo_shared_bases_isolated_to_zones_in_hierarchy`.

### B5. Score-1 dead-end for valid repo-level hierarchy

**Symptom.** A documented repo-level base with one subclass per zone
scored 1, because the score-3 path required zone-local fan-out (≥ 2
zone-local subclasses) before checking `repo_documented_bases`.

**Fix.** Reordered scoring: score 3 (and 4) is checked first based on
`repo_documented_bases`, before the zone-local-fan-out branch. Test:
`test_repo_level_base_with_one_subclass_per_zone_scores_three`.

### B6. `reraise_chain` captured direct propagation as wrap

**Symptom.** `except Exception as exc: raise exc` was tagged as a
`reraise_chain`, inflating wrap counts.

**Fix.** Wrap detection now requires the raised name to be class-like
(builtin, suffix-matching, known custom, or alias-resolved to one).
Direct propagation through a local variable does not fire. Test:
`test_reraise_local_variable_is_not_a_wrap`.

### B7. `github_failure_surface` required local raise

**Symptom.** A file that delegates to `wea_cli.gh` and lets `GhError`
propagate was not flagged as a github surface because it had no local
raise.

**Fix.** File flags now derive purely from imports/usage indicators; the
local-raise requirement was removed. Tests:
`test_github_failure_surface_flag_for_delegated_caller` and
`test_github_failure_surface_flag_for_dotted_import`.

### B8. `import wea_cli.gh as gh` was missed by visit_Import

**Symptom.** `visit_Import` only set `gh_import_seen` for `from
wea_cli.gh import ...`, not the dotted-import form.

**Fix.** `visit_Import` now checks `alias.name == "wea_cli.gh"` or starts
with `wea_cli.gh.`. Test: `test_github_failure_surface_flag_for_dotted_import`.

### B9. Imported alias raises were undetected

**Symptom.** `from pkg import FooError as E; raise E()` was missed —
neither `_is_exception_like("E")` nor `is_known_custom` matched, so the
raise fell through.

**Fix.** Added an `alias_resolved` lookup against `self._imports`. When
the alias resolves to a class-like target, the raise is recorded with
the canonical resolved name as the symbol. Test:
`test_imported_alias_raise_is_classified`.

### B10. Aliased symbol was not canonicalized for score lookup

**Symptom.** When a custom raise resolved through an alias, the
recorded `symbol` was still the local name (`E`), so the score logic
didn't match it against the declared subclass name (`FooError`).

**Fix.** `symbol = alias_resolved or short`. Tests:
`test_imported_alias_raise_is_classified` and
`test_alias_with_exception_suffix_resolves_to_canonical`.

### B11. Repo-level documented bases scored zones with no local usage

**Symptom.** Zone A raises `AError`; zone B declares an unused
`BError` under the same base; zone B scored 3.

**Fix.** `repo_documented_bases` now requires the base or one of its
zone-local descendants to be raised in the current zone. Test:
`test_repo_documented_base_requires_zone_local_usage`.

### B12. Handler stack leaked into nested functions/classes

**Symptom.** A function defined inside an except handler raises an
exception in its body — that raise was being classified as `in_handler`
even though it executes outside the handler scope.

**Fix.** `visit_FunctionDef`, `visit_AsyncFunctionDef`, and a
`_visit_classdef_isolated` helper save/restore the handler stack at
function/class boundaries. Tests:
`test_nested_function_in_except_does_not_inherit_handler` and
`test_method_in_class_in_except_does_not_inherit_handler`.

### B13. Imports defined inside try bodies arrived too late

**Symptom.** `try: from pkg import FooError as E ...; except: raise E()`
ran the handler before the body was visited, so `_imports["E"]` was
empty when the alias raise was classified.

**Fix.** `FileVisitor.__init__` now does a one-pass `ast.walk` over
the tree to pre-collect all imports before any visit happens. Test:
`test_alias_introduced_in_try_body_is_resolved`.

### B14. Zone label spelling produced extra empty zones

**Symptom.** `--zones ./src` produced a `summary.by_zone` with two
keys: `./src` (empty) and `src` (with files).

**Fix.** Added `_normalize_zone(...)` and the summary builder folds
both spellings into the canonical zone label. The bare `.` spelling is
preserved as the original label so the operator can read the zone they
asked for. Tests: `test_dot_zone_scans_whole_root`,
`test_dot_prefixed_zone_resolves`, `test_zone_label_normalized_in_summary`.

### B15. Flow-control raises were invisible

**Symptom.** `raise StopIteration()` and `raise KeyboardInterrupt()`
fell through both `_is_builtin_exc` (their names don't end in
Error/Exception) and the custom-raise branch (they are excluded by
`_FLOW_CONTROL | _INTERRUPT_LIKE`), so they produced no detection at
all.

**Fix.** Added an explicit branch that records them as
`raw_builtin_raise_at_boundary` with confidence `low` and an
`extra.flow_control: true` annotation. Test:
`test_flow_control_raise_is_detected_at_low_confidence`.

### B16. Handler-bound variables that look like classes

**Symptom.** `except Exception as TaskError: raise TaskError` was
classified as a class wrap because `TaskError` ends in `Error`. Direct
propagation was being inflated into wrap counts.

**Fix.** The handler stack now stores `(types, bound_name)`. A raise
of a name in the active handler's bound set is classified as
`bare_reraise` (with an `extra.bound_name` annotation), never as
`custom_raise` or `reraise_chain`. Test:
`test_handler_bound_variable_raise_is_propagation_not_wrap`.

### B17. Aliases whose local name was already exception-like

**Symptom.** `from pkg import FooError as BarError; raise BarError()`
recorded `symbol = BarError` because the alias-resolution guard
short-circuited when the local name itself looked like an exception.

**Fix.** Removed the `not _is_exception_like(raised_name)` guard;
aliases are now always resolved against the import map regardless of
the local name's suffix. Test:
`test_alias_with_exception_suffix_resolves_to_canonical`.

### B18. Zone paths could escape the repo root

**Symptom.** `--zones ..` (or an absolute path) crashed inside the
walker at `path.relative_to(root)` after silently scanning external
files for several seconds.

**Fix.** Both the harness and the CLI preflight reject zones that
resolve outside the root; `skipped_files` records the rejection with
a clear reason. Tests: `test_zone_escaping_root_is_rejected` and
`test_main_rejects_zone_escaping_root`.

### B19. Multi-level hierarchies marked as padded

**Symptom.** A base `BaseError → MidError → LeafError` where only the
leaves are raised was tagged padded because `base_to_subs[BaseError]`
only contains direct children (`MidError`).

**Fix.** Both zone-local and repo-level usage checks compute
*transitive* descendants and look for any descendant in the raised
set. Test: `test_multilevel_hierarchy_with_leaf_raises_scores_two`.

## Cross-checks against the pre-impl redteam

### S1. "Repo-wide" claim

**Status.** The harness defaults to `src/wea_cli` and `scripts/`. `--zones`
accepts arbitrary additional Python zones. Verified live with the default
config plus the JSON `scope.zones` field that records what was scanned.

### S2. Pilot pick

**Status.** `src/wea_cli` was picked because of user-facing surface, not
size. The H1 hardening recommendation applies to the chosen zone and the
post-impl redteam confirms it generalizes (the `repo_shared_bases`
machinery would activate when a second zone subclasses `WeaCliError`).

### S3. Cosmetic-win immunity

**Status.** Verified two ways:

1. The score `2` requires `len(shared_zone_bases) >= 1` AND the base must
   have at least 2 zone-local subclasses.
2. The `padded_hierarchy_bases` filter removes any base whose subclasses
   are never raised in the scanned tree. `test_padded_hierarchy_does_not_score_two`
   exercises this directly.

### S4. Score `4` reachability

**Status.** Confirmed unreachable without `--enforced-check`. Test
`test_score_never_four_without_enforced_check` proves it. The CLI flag is
required, never inferred.

### S5. Test directory exclusion

**Status.** Default scope excludes `tests/`. Skipping is reported in
`scope.zones` (which lists only the zones actually scanned). A scoped run
that includes `tests` would report the test-side error classes; this is
opt-in.

### S6. Forward-compatible JSON

**Status.** `harness_version: "v0"` is present in every report. Future
versions will bump it. Diff consumers should anchor on `summary.by_kind`
and `summary.exception_topology_score` for stability.

### L1. Cross-zone name collisions

**Status.** Acknowledged limitation. The `inheritance` graph uses bare
names. The live scan does not currently exhibit any collision; if a future
zone declares a class with the same short name as a `src/wea_cli` class,
the limitations list will steer the reviewer to the right diagnosis.

### L2. Dynamic class creation

**Status.** Acknowledged. Live scan finds zero metaclass/`type()`-based
exception generation in WEA. Documented in `limitations`.

### L3. Re-raise pattern brittleness

**Status.** Tightened during implementation. `reraise_chain` records both
inner (handler) and outer (raise) class names plus the `from_clause`
flag. Tests verify the standard wrap pattern and the bare reraise pattern
do not collide.

### L4. CLI/GitHub surface heuristic

**Status.** Annotation-only, as planned. Score is unaffected. Verified
by inspecting `release.py` and `cli.py` flags in the live JSON.

### L5. Built-in raise list

**Status.** Switched from a hand-rolled list to the Python `builtins`
namespace plus an `Error`/`Exception` suffix fallback. This made the live
scan find more builtins than the early hand-rolled list would have.

### L6. Stable summary

**Status.** Verified via `test_output_is_deterministic_across_runs`. Two
runs against the same input produce byte-identical JSON when
`scan_date` is fixed.

## Implementation-time decisions

1. **Two-pass scan with cached AST**: parse once per file, reuse the
   `ast.Module` for the second pass with the known set. Avoids re-parsing
   170+ files.

2. **`raised_class_names` only counts boundary-class symbols** (custom
   raises and built-in raises), not bare reraises. A `raise` without an
   operand cannot inform "what classes are actually raised".

3. **`enforced_check` is a string, not a boolean**, so an operator can
   pin the path of the checker for future audit (e.g.
   `"scripts/check_wea_cli_error_base.py"`).

4. **The CLI prints stderr warnings for parse errors and unused excludes**,
   so a silent JSON consumer does not lose diagnostic information.

## Residual risks acknowledged

- The harness undercounts when a file uses `type(...)` to build an
  exception class. Documented as a `v1` upgrade candidate.
- A zone with no `__init__.py` and a single Python file is reported with
  full counts; the heuristic for "looks like a CLI surface" is based on
  imports/decorators and may flag library files that happen to use
  `argparse` for tooling. Annotation-only, so impact is limited.
- The pilot's H1 change (`WeaCliError`) is a strict subclass of
  `RuntimeError`. Any code path using `except RuntimeError` continues to
  catch it. There is no behavior change at the call site.

## Final acceptance checklist for Agent0

- Harness JSON envelope is stable, version-stamped, and deterministic.
- Inheritance and detection logic survive a second-pass refactor.
- Two checkpoint artifacts land in the PR (baseline + with-h1).
- Pilot decision is documented with explicit anti-gaming disclosures.
- Tests cover detection, scoring, scope, stability, and CLI black-box.
- `pytest tests/ -q` passes against the full suite.
- The H1 change is backwards compatible: every `WeaCliError` subclass is
  still a `RuntimeError`.
