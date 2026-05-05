# Error topology census — logic note (pre-implementation)

This note describes the design before any scanner code is written. It is the
code-free spec the implementation must follow.

The scope of this task is two-part:

1. A repo-wide Python error-topology census. Designed to apply to the whole
   repository, run as a single command, emit a stable summary, and let
   Circle-1 compare future checkpoints.
2. A narrow `src/wea_cli` pilot: analyze the zone first, then either justify
   census-only or land a tight, well-tested hardening step inside one
   sub-surface of `src/wea_cli`.

The census must work on more than `src/wea_cli`. `src/wea_cli` is the first
pilot, not the boundary of the system.

## Why error topology, why now

The Circle-1 v0 model treats `exception_topology_score` as part of
`boundary_contracts`. Today WEA has no repo-wide map of:

- which custom exception classes exist;
- whether they share a base inside a zone or across zones;
- where boundary code raises raw built-ins (`ValueError`, `FileNotFoundError`,
  `RuntimeError`, etc.) at user- or protocol-facing surfaces;
- where catches are broad (`except Exception`, `except BaseException`,
  bare `except:`);
- where errors are wrapped and re-raised vs. swallowed.

Without this map, every code review re-derives the same picture from scratch.
A repeatable scan replaces ad hoc reasoning with a structured artifact and
gives the next checkpoint a number to move.

## What the census is, and what it is NOT

The census is a structural scanner. It reports observable shapes in Python
source under repo zones.

The census is NOT:

- a runtime call-graph analysis;
- a typing or `mypy`-style verifier;
- a guarantee that any raise site is "wrong";
- a verdict on which exceptions agents should use going forward;
- proof that WEA is colder. Only a future checkpoint comparison can hint at
  cooling, and even then with the documented caveats from
  `cooling_metrics_v0.md`.

A high score on this scanner does not mean the repo is well structured. A low
score does not mean the repo is broken. The score is a steering signal, and it
must be read with the per-finding evidence next to it.

## Zones (what gets scanned)

The scanner operates on declared zones. A zone is a directory glob plus a
short identifier. The session-1 zones are:

- `src_wea_cli` -> `src/wea_cli/**/*.py`
- `scripts` -> `scripts/**/*.py` (includes `scripts/circle1/`)
- `tests` -> `tests/**/*.py` (reported but its score is informational only;
  test code legitimately raises and catches in shapes that would be wrong
  in production code)

Zones are disjoint by design. A sub-surface like `scripts/circle1/` is not a
separate zone, because overlapping zones would double-count in repo totals.
Tracking such a sub-surface across checkpoints is done by filtering
`findings` records by file path, not by declaring an overlapping zone.

Other Python zones (`domains/`, `gunnery/`, `agent0/`, future code) are not
scanned in v0 to keep the pilot honest. Adding them is a config change, not a
code change. Every excluded directory is listed in the output under
`excluded_paths` with a short reason. Not surfacing exclusions would be a
gaming mode that the issue explicitly forbids.

Files that fail to parse are reported under `parse_errors` in the same output
record. They are NOT silently dropped, because that would let a broken file
quietly improve the picture.

## What the scanner extracts

For every Python file in scope, the scanner walks the AST and collects four
kinds of finding:

1. **Custom exception classes.** Class definitions whose declared bases
   (resolved by the textual base name found in the AST) include a known
   exception type, either a Python built-in (`Exception`, `RuntimeError`,
   `ValueError`, `IOError`, `OSError`, `KeyError`, `LookupError`,
   `TypeError`, `BaseException`, `NotImplementedError`) or a name that
   matches the heuristic `*Error` / `*Exception`. For each class the scanner
   records: name, parent base names, file path, line number, whether the
   class body is a single-statement docstring/`pass` placeholder, and a
   bucket label (`builtin_subclass`, `custom_subclass`, `placeholder`).

2. **Raise sites.** `raise X(...)` and `raise X` statements. For each site
   the scanner records: file path, line number, exception name, whether the
   exception name resolves to a built-in, whether the raise is inside an
   `except` block (i.e. potentially a wrap/re-raise) and, if so, whether it
   uses `from`. Bare `raise` (re-raise inside `except`) is recorded as
   `kind=re_raise`.

3. **Catch sites.** Every `except` clause. For each site the scanner records:
   file path, line number, the caught type names, a `breadth` label
   (`bare`, `base_exception`, `broad_exception`, `narrow_specific`,
   `narrow_tuple`), and a `disposition` label (`re_raise`, `transform`,
   `swallow`). Disposition mirrors Python semantics: an except handler
   that runs to completion without raising consumes the caught exception,
   so any non-raising handler is `swallow` (whether the body is `pass`,
   `return ...`, a fall-through log call, an `append`, etc.). The only
   distinctions among raising handlers are `re_raise` (bare `raise` or
   raise of the bound exception) and `transform` (raise of a different
   exception). Walking stops at nested function/class/lambda/except-handler
   scopes; raises inside helper calls (e.g. `_log_and_raise(exc)`) are not
   detectable from AST and are recorded as `swallow` in v0. Tuple
   handlers that include `Exception` or `BaseException` are classified by
   their broadest member (`broad_exception` or `base_exception`
   respectively), not as `narrow_tuple`, so they are correctly counted in
   `broad_catch_count`. Swallowing is detected when the body is a single `pass`
   or a `continue` with no further effect; transforming is detected when the
   body raises a different exception (with or without `from`); re-raising is
   detected when the body raises the bound name or uses bare `raise`.

4. **Boundary surfaces.** A coarse heuristic that flags raise sites in
   user- or protocol-facing positions:

   - functions whose name signals a CLI or GitHub edge: names starting
     with `cmd_`, `_cmd_`, `handle_`, names ending in `_main`, the
     function `main`;
   - functions in modules named `cli`, `gh`, `health`, `spawn`,
     `release`;
   - any function inside a module that constructs
     `argparse.ArgumentParser(...)` at any nesting (read-only AST scan,
     no execution; bare `import argparse` is intentionally NOT enough,
     because library modules sometimes import `argparse` only for type
     hints).

   This is intentionally coarse; it is meant to point reviewers at the
   surfaces most worth re-examining, not to draw a true call graph.

The class inheritance graph is built per zone. A zone is said to have a
shared custom base when at least two distinct custom classes in that zone
inherit (directly or transitively, traversing classes the scanner saw) from
the same custom (non-built-in) class defined inside any scanned zone.

## Output shape (stable for checkpoint comparison)

The scanner writes one JSON document.  The top-level shape is:

- `scan_date` (`YYYY-MM-DD`)
- `repo_sha` (string, the resolved commit if known, else empty)
- `tool_version` (an integer schema version that the scanner bumps when the
  output shape or the score rubric changes; bumping must be paired with a
  baseline regeneration)
- `scope`: list of declared zones with their globs
- `excluded_paths`: list of `{path, reason}` records (statically declared)
- `unscanned_python_dirs`: list of `{path, py_file_count}` records,
  auto-discovered at scan time. A top-level directory containing `.py`
  files that is neither scanned nor declared in `excluded_paths` shows
  up here so checkpoint readers can see drift if a new top-level Python
  area appears later. Obvious infrastructure (`.git`, `__pycache__`,
  etc.) is filtered out.
- `parse_errors`: list of `{path, error}` records
- `summary`:
  - per zone: `custom_class_count`, `placeholder_class_count`,
    `raw_builtin_raise_count`, `wrap_raise_count`, `re_raise_count`,
    `broad_catch_count`, `bare_catch_count`, `swallowed_catch_count`,
    `boundary_raise_count`, `shared_base_zone_score` (0..2)
  - repo-wide: same counters aggregated, plus a derived
    `repo_exception_topology_hint` in `{0, 1, 2}` (the v0 rubric only goes
    that high on mechanical evidence; values 3 and 4 require human review of
    documentation and enforcement and are intentionally not assigned by the
    scanner)
- `findings`: per-finding records sorted by `(zone, file, line, kind)` so
  diffs between checkpoints stay readable. `findings` is the substrate
  reviewers actually read. Counters above are derived from it.

The summary section is intentionally separated from `findings` so a
checkpoint comparison can diff counters without diffing every line move.

The top-level keys and the per-zone counter keys are frozen; adding a new
counter requires bumping `tool_version` so any consumer notices.

## Per-zone score (mechanical part of the rubric)

The scanner only assigns the mechanical part of the v0 rubric:

- `0` — zero custom exception classes in the zone;
- `1` — one or more custom classes in the zone with no shared custom base;
- `2` — at least one shared custom base used by two or more custom classes
  inside the zone (or by one class in the zone and another in a directly
  scanned related zone).

Scores `3` and `4` require human evidence of documented usage and
enforcement (e.g. CI gates checking that public surfaces only raise the
shared base). The scanner intentionally refuses to assign them. The per-zone
output therefore carries a `shared_base_zone_score` clamped to `0..2`.

The repo-wide `repo_exception_topology_hint` is the **minimum** of the
per-scored zones (`tests` excluded). Taking the minimum, not the maximum,
prevents one warm zone from masking a cold one. The issue explicitly forbids
"creating a base exception that real failure paths do not use" being
counted as topology improvement; the minimum rule is the mechanical defense.

## CLI shape

The scanner is a stand-alone Python script under `scripts/circle1/`. It
follows the existing scanner style in that directory (`task_contract_extractor.py`,
`zone_grammar.py`):

- stdlib only (`ast`, `json`, `argparse`, `pathlib`);
- `from __future__ import annotations`;
- module docstring;
- `main(argv)` returning an integer, called from a `__main__` guard;
- importable for testing.

CLI flags:

- `--root <path>` — repo root (defaults to the current working directory);
- `--out <path>` — output JSON path (defaults to stdout);
- `--zones <zone>[,<zone>...]` — limit scan to a subset (defaults to all
  declared zones);
- `--scan-date YYYY-MM-DD` — override the scan date (for deterministic test
  runs);
- `--repo-sha <sha>` — override the recorded SHA (for deterministic test
  runs).

The scanner never reads or writes ledger state, GitHub data, or CI files.

## src/wea_cli pilot

The pilot scope is `src/wea_cli/**/*.py`. Reasons it is the first target:

- it is a large user-facing surface, so error shape directly affects exit
  codes and CLI messages;
- it already mixes three error styles: zone-local custom classes
  (`PushError`, `GhError`, `IssueEditError`), raw built-ins
  (`ValueError`, `FileNotFoundError`), and one broad swallow
  (`except Exception: pass`);
- the three custom classes share no base, so the zone is currently at
  rubric score `1` even though it has the structural ingredients for `2`;
- a tight one-file change can move `src_wea_cli` from `1` to `2` without
  touching any catch sites.

### Pilot recommendation: introduce `WeaCliError` shared base

The minimal hardening step is a new `src/wea_cli/errors.py` defining one
class:

- `WeaCliError(RuntimeError)` — the shared base for any `wea` CLI failure
  whose handling diverges from a normal runtime error.

The three existing custom classes (`PushError`, `GhError`, `IssueEditError`)
are then re-rooted so their MRO becomes `Class -> WeaCliError ->
RuntimeError -> Exception`.

Because `WeaCliError` itself extends `RuntimeError`, every existing `except
RuntimeError`, `except GhError`, `except PushError`, `except IssueEditError`
catch site continues to behave exactly as before. No catch site needs to
change, no exit code shifts, no public string changes.

This is a "shared base in at least one zone" change. It satisfies the v0
score `2` mechanical signal. It does NOT claim score `3` because there is
no repo-level base, no documentation that all `wea` CLI failures must use
the base, and no enforcement check.

The pilot deliberately does NOT:

- introduce a hierarchy of subclasses;
- rename or remove the three existing classes;
- migrate any raw `ValueError` or `FileNotFoundError` raise sites; those are
  named in the census output as candidates for a future, separate task;
- collapse the broad `except Exception: pass` block in `cli.py` near line 897;
  that swallow is a separate hardening surface and the issue forbids
  rewriting `cli.py` broadly.

### Pre-implementation spec redteam

Issues considered before writing the pilot code:

1. Does adding `WeaCliError` change observable CLI behavior?
   - No. `WeaCliError(RuntimeError)` keeps every existing `except` path
     intact. `__str__`, `__repr__`, exit codes, and message text are
     unchanged. New tests assert isinstance over the existing classes.

2. Does the new file violate the existing `src_wea_cli` empirical zone
   shape (module docstring, `from __future__ import annotations`, no main
   guard)?
   - No. The new module follows that exact shape. The zone-grammar
     scanner already encodes the three checks, and the new file is
     written to satisfy them.

3. Is "shared base used by three classes in one zone" actually a score `2`
   under the v0 rubric, or is the rubric demanding more evidence?
   - The rubric text is: "shared base in at least one zone". Three
     subclasses inside `src_wea_cli` rooted on a custom `WeaCliError`
     defined inside the same zone is a literal match. The pilot does not
     attempt to claim score `3` (which would require repo-level usage and
     documented contracts) or score `4` (enforcement).

4. Could the pilot be gamed by having `WeaCliError` exist but no real
   failure path actually use it?
   - The three classes that re-root onto it ARE the real failure paths
     for: GitHub CLI failures (`GhError`), `git push` failures
     (`PushError`), and safe label-edit rollbacks (`IssueEditError`).
     They are the only custom classes in the zone. A new class added in
     the future that does not extend `WeaCliError` will be visible in
     the census output as a "non-conforming zone-local exception"
     candidate at the next checkpoint.

5. Could the census itself be gamed?
   - Yes, in three ways the issue calls out:
     a. Excluding `scripts/` to inflate the score. The scanner records
        `excluded_paths` explicitly and uses the **minimum** of per-zone
        scores for the repo-wide hint, so excluding a zone cannot raise
        the repo-wide hint.
     b. Surface-not-substance: counting files with the word "Error" in
        their name. The scanner only counts class definitions whose
        declared bases include a known exception type, not filenames or
        identifiers with "Error" in them.
     c. Empty topology padding: defining `WeaCliError` and never using
        it. The scanner's zone score is gated on at least two custom
        subclasses transitively rooted on the candidate base, not on the
        existence of the base alone.

6. What if a future Python version changes `ast` node shapes for `except*`
   (PEP 654) or for `raise from`?
   - The scanner only reads existing fields (`type`, `name`, `body`,
     `cause`). `except*` is recorded as `breadth=narrow_specific` with a
     `pep654=True` flag for transparency. The scanner does not require
     these fields to be present; missing fields are recorded as `None`.

### Pre-implementation logic redteam

Logic-level concerns considered before coding the scanner:

1. **Inheritance resolution is purely textual.** The scanner does not
   import modules; it reads AST. A class declared as `class X(Y):` where
   `Y` is an alias from another import is recorded with parent name `Y`,
   even if `Y` resolves to a built-in via `from ... import ... as Y`. This
   is acceptable for a v0 scanner and is documented in the output. Both
   the per-zone score and the repo-wide hint are conservative because of
   this: a class is treated as "having a shared custom base" only when
   the base name is itself defined as a class in the scanned tree. Bases
   that are imported from outside the scanned tree are recorded but do
   not count toward score `2`.

2. **Star imports.** `from foo import *` makes inheritance resolution
   ambiguous. The scanner does not attempt to resolve them. It records
   any such import in `parse_errors` as a soft warning. The session-1
   zones currently contain no star imports, so this is preventive.

3. **Decorator-based exception declarations.** The scanner does not look
   at decorators. WEA does not currently use any.

4. **Conditional class definitions inside `try/except`.** The scanner
   walks the full module body recursively; classes defined inside `try`
   blocks are still found.

5. **Test code raising for fixtures.** `tests/` is scanned but its
   per-zone score is excluded from the repo-wide hint. `tests/` raise
   sites and broad catches are recorded so future test-side hygiene work
   has a baseline, but they do not affect the headline number.

6. **Stability across runs.** Counters depend only on AST shape and
   declared zones. `findings` is sorted lexicographically. Two runs over
   the same tree produce byte-identical JSON when `--scan-date` and
   `--repo-sha` are pinned. The scanner does not include timestamps
   inside individual findings.

7. **The repo-wide hint is a minimum, not an average.** A zone with no
   custom errors at all (score `0`) drags the repo-wide hint down to `0`
   even if every other zone is at `2`. This is intentional; the rubric
   asks whether the repo as a whole has shared error structure, not
   whether one zone does. A scanned zone with zero Python files that
   define exception classes is treated as "no signal" rather than
   "score `0`" and is excluded from the minimum (this is the only
   exception, and it is documented in the output).

8. **No silent drops.** Files that fail to parse are recorded under
   `parse_errors`. Files explicitly excluded from a zone are recorded
   under `excluded_paths`. The summary documents both counts.

## Monitoring and checkpoint plan

The PR commits two artifacts under `domains/circle-1/error_topology/`:

- `baseline.json` — the census output captured at the PR base commit.
- `wea_cli_pilot.md` — the pilot analysis, including this logic note's
  pilot section in long form, the chosen hardening step, post-
  implementation redteam notes, and the next checkpoint plan.

At the next Circle-1 checkpoint after this PR lands, Agent0 re-runs the
scanner and writes a second JSON document next to the baseline. The two
files together let Circle-1 ask:

- did `src_wea_cli` actually move from rubric score `1` to `2` under the
  scanner's mechanical rule?
- did the count of raw built-in raises at boundary surfaces stay flat,
  shrink, or grow?
- did any new custom exception classes land that ignore `WeaCliError`?
- did the `scripts` zone change at all (it has no pilot in this PR)?

If no eligible Python error-handling changes land before the next
checkpoint, the inconclusive policy in the issue applies.

## Out of scope for this PR

- repo-wide exception hierarchy (the issue explicitly forbids this);
- broad rewrite of `src/wea_cli/cli.py`;
- migration of raw `ValueError` / `FileNotFoundError` to `WeaCliError`;
- collapsing the existing `except Exception: pass` swallow in `cli.py`;
- any change to ledger data, Tide settlement, GitHub workflows, or issue
  templates;
- a typed `Result`-style refactor;
- changes to `gunnery/`, `domains/`, `agent0/`, or any zone outside
  `src/wea_cli/` and `scripts/circle1/`.
