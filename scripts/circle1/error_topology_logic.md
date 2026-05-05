# Circle-1 error topology census logic

This is the code-free architecture note for `error_topology_census.py`. It is
written before implementation so the spec can be redteamed against the contract,
not against the code.

## Actors

Agent0 runs the census during checkpoint work or before/after a hardening PR
that touches error handling. Worker agents may run it before submitting Python
changes. Future Circle-1 sweeps read the compact summary and decide whether the
`exception_topology_score` moved.

## Inputs

The required input is the repo tree. The census walks Python files under the
configured zones. Default zones:

- `src/wea_cli/**/*.py`
- `scripts/**/*.py`

The CLI accepts an explicit `--zones` override and an explicit `--exclude`
list. Any zone outside the defaults must be named on the CLI; the harness does
not silently widen scope.

`tests/` is **not** a default zone because test exception classes
(`TestMalformedJsonError`, mock errors, `pytest.raises(...)` plumbing) speak a
different dialect than production failure paths and would muddy the topology
score. `tests/` may still be scanned via `--zones tests` when the question is
explicitly about test-side error contracts.

The harness must not import scanned modules, execute scanned code, launch
subprocesses, call GitHub, mutate ledger data, or enforce CI policy. It is an
AST-only census.

## Detected kinds

Each detection is one of these kinds. Every detection records `path`, `line`,
`col`, `symbol`, `snippet`, `confidence`, and `reason` so that later
checkpoints can be compared without rerunning the harness against the same
commit.

1. **`custom_exception_class`** — a `class` whose direct or transitive base
   chain ends in something that looks like `Exception`/`Error`. The detection
   captures the class name, its direct bases, the module-relative path, and a
   `has_docstring` flag.

2. **`raw_builtin_raise_at_boundary`** — a `raise X(...)` where `X` is a
   built-in exception (`ValueError`, `TypeError`, `RuntimeError`,
   `FileNotFoundError`, `KeyError`, `OSError`, `LookupError`, `NotImplementedError`,
   `AssertionError`, `Exception`). These are ambiguous failure surfaces because
   callers cannot tell whether the raise is a programmer-error sentinel, a
   user-input rejection, or a protocol violation. They are reported with
   `confidence: high` because the AST proves the literal class name; the
   `at_boundary` qualifier is opportunistic — see below.

3. **`custom_raise`** — a `raise X(...)` where `X` is a name that looks
   custom (`*Error`/`*Exception`, not a built-in, not a Python warning class,
   not `StopIteration`-family flow control). The class may live in this file
   or be imported. Cross-file resolution is best-effort: same-file class names
   are confidence `high`; imported names are confidence `medium`; aliased or
   dynamic names are `low`.

4. **`broad_catch`** — `except Exception`, `except BaseException`, bare
   `except:`, or an `except` tuple containing one of those. Bare `except:` is
   reported separately as a sub-reason because it also catches
   `KeyboardInterrupt` and `SystemExit`.

5. **`reraise_chain`** — an `except H as e: ... raise X(...) from e` pattern
   inside the same handler. This is the opposite of `broad_catch`: it shows
   intentional wrapping. The detection records the inner `H` and the outer
   `X` so reviewers can see whether the wrap promotes a built-in to a custom
   class (good) or rebrands a custom class as a built-in (suspicious).

6. **`bare_reraise`** — `raise` with no operand inside an `except` handler.
   This is a propagation, not a wrap, and is recorded so it does not get
   confused with `custom_raise`.

7. **`cli_failure_surface`** — file contains a `def main(` or
   `argparse.ArgumentParser` or a click decorator AND contains at least one
   `raise` reachable from outside a `try`. The flag is per-file, not
   per-line. Confidence is `medium` because static analysis cannot prove
   exception escape paths through arbitrary code.

8. **`github_failure_surface`** — file imports `wea_cli.gh`, references a
   subprocess call where the literal command is `gh`, calls `api.github.com`,
   or uses one of the known GitHub client method names. Confidence `medium`
   for the same reason.

`cli_failure_surface` and `github_failure_surface` are file-level annotations,
not per-raise tags. They tell reviewers which files sit on a user-visible
boundary so the topology score is read with the right lens.

## Inheritance graph

The harness builds a name-only inheritance graph from the
`custom_exception_class` detections. Nodes are class names; edges are direct
`(child -> base)` pairs. The graph is intentionally name-based: the harness
does not resolve fully-qualified names across modules, because doing so
correctly would require an import resolver, which is out of scope for an
AST-only census.

The graph is reported as a flat dict
`{ class_name: { "bases": [...], "subclasses": [...] } }` so that future
checkpoints can detect when a new shared base appears or when an old one
becomes unused. `unknown` bases (names that look like `Error`/`Exception` but
were never declared as a class in any scanned file) are still recorded as
`bases` with no subclass entry, so reviewers can see when a zone subclasses an
unscanned third-party error class.

## Per-file ownership

Every detection carries `path` (repo-relative, forward slashes) and `zone`
(one of `src/wea_cli`, `scripts`, or `other`). The default scope produces only
the first two. `other` exists for when a future caller passes
`--zones src/wea_cli,scripts,domains/circle-1` so the per-zone summary still
counts everything.

## Stable summary

The summary is the canonical comparison unit between checkpoints. It holds:

- `total_files`, `files_with_detections`, `parse_errors`, `skipped_files`
- `by_kind`: per-kind `{files, detections}` map
- `by_zone`: zone -> `{total_files, files_with_detections, by_kind, score_inputs}`
- `score_inputs`: per-zone counts that the `exception_topology_score` rubric
  consumes (`custom_exception_classes`, `class_with_shared_base_zone`,
  `class_with_shared_base_repo`, `documented_usage`, `enforced_check`)
- `exception_topology_score`: the v0 0..4 rubric value, computed per zone and
  reported again as a `repo` aggregate. The repo value is the **minimum**
  across non-empty zones, never the average, so a single zone with no
  hierarchy cannot be hidden by a strong neighbour.

`score_inputs` is intentionally exposed so a future tracker can recompute the
score without rerunning the harness, and so reviewers can see why a number is
what it is.

## Stability rules

The JSON output is deterministic for a fixed input tree:

- files are sorted by repo-relative path
- detections inside a file are sorted by `(line, col, kind, symbol)`
- `exception_classes` is a flat list sorted by `(path, line)`
- `inheritance` keys are sorted alphabetically
- `skipped_files` is sorted by path

`scan_date` is the only field that changes between identical reruns on the
same commit, and it is overrideable with `--scan-date` for reproducible
checkpoints.

## Scoring rubric (per zone)

`exception_topology_score` follows the v0 spec verbatim:

- `0` — no custom exception classes detected in the zone
- `1` — at least one custom exception class, no shared base
- `2` — at least one shared base used by at least two classes inside the zone
- `3` — repo-level shared base (a base whose subclass set spans more than one
  zone) AND the base class file contains a docstring describing usage
- `4` — `3` plus an `enforced_check` artifact: a CI workflow, pre-commit hook,
  or `scripts/check_*.py` that names the base class

`enforced_check` is an explicit configuration input. The harness never auto-
discovers enforcement and never claims `4` without an operator-supplied
`--enforced-check` flag. This protects against the gaming mode of declaring a
hierarchy and calling it enforced because a test imports it.

## Anti-gaming rules

- Excluded paths must be reported in `skipped_files` with a reason. The
  harness fails loudly if a `--exclude` pattern matches zero files (the
  pattern is then suspicious, not silent).
- The denominator is per-zone and per-kind. A zone cannot improve its score
  by moving warm files into another zone unless the other zone is also
  scanned.
- A custom exception class with zero raises in the scanned tree is flagged
  with `unused: true`. This catches the "create a base class nobody raises"
  pattern.
- A shared base whose subclasses are never raised is flagged with
  `padded_hierarchy: true`. This catches the "wrap everything in one generic
  custom exception" pattern.
- The harness does not promote a zone to score `3` without observing actual
  raises of the base class or its subclasses inside the scanned tree.
- The CLI prints a one-line warning when `parse_errors > 0` so a silent JSON
  consumer cannot ignore unparsed files.

## Failure paths

Unreadable or unparsable Python files appear in `skipped_files` with a
reason. They do not produce fake detections.

A missing zone directory makes the CLI fail with a non-zero exit code instead
of producing an empty zone summary. This protects callers from comparing a
broken run against a real one.

A coverage-style "everything is fine" report is impossible: empty zones are
reported as `total_files: 0` so the next sweep can spot the regression.

## Accepted examples

- `src/wea_cli/gh.py: GhError(RuntimeError)` is detected as a
  `custom_exception_class` with base `RuntimeError`. With two more sibling
  classes also subclassing `RuntimeError`, the `src/wea_cli` zone scores
  `1` (no shared custom base).

- After `src/wea_cli/errors.py` introduces `WeaCliError(RuntimeError)` and
  the three existing classes inherit from it, the zone scores `2` because
  the inheritance graph shows three classes sharing one zone-local base.

- A wrap pattern `except json.JSONDecodeError as e: raise GhError(...) from e`
  appears as both a `reraise_chain` and a `custom_raise` detection on the
  same line, and the `reraise_chain` records inner `JSONDecodeError` and
  outer `GhError`.

## Rejected examples

- A report that lists files containing the word `Error` is not a topology
  census.

- A score of `3` claimed without observing any real raise of the base class
  or its subclasses is rejected.

- Excluding `scripts/` to make the picture look better is forbidden; if the
  zone is excluded, the exclusion appears in the report.

- A CI gate, Tide change, ledger mutation, GitHub Actions change, or
  issue-template change is outside scope.
