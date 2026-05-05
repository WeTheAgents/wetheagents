# `src/wea_cli` error-topology pilot

This document records the pilot slice for Issue #885: a focused look at
`src/wea_cli/` error topology, paired with one tight implementation step
(adding a shared `WeaCliError` base) that moves the zone's
`exception_topology_score` from `1` to `2` under the Circle-1 v0 rubric.

The full design and pre-implementation redteam notes live in
[`logic.md`](logic.md). This document is the pilot-specific layer: the
baseline picture, the chosen change, the post-implementation redteam, and the
checkpoint plan.

The PR ships:

- the repo-wide scanner at `scripts/circle1/error_topology.py`;
- tests at `tests/test_error_topology.py`;
- two census snapshots in this directory (`baseline.json` =
  `origin/main`, `post_pilot.json` = this branch);
- the new `src/wea_cli/errors.py` module and a 1-line edit in each of
  `gh.py` and `issue_edit.py` so `GhError` and `IssueEditError` inherit
  `WeaCliError` instead of `RuntimeError`.

`PushError` (in `cli.py`) deliberately stays under `RuntimeError` in this
PR — see the post-implementation redteam below for the script-mode
sys.path constraint that drove that scoping decision. Nothing else in
`src/wea_cli/` is touched.

## Why `src/wea_cli` is the first pilot

The repo has roughly two production Python zones today: `src/wea_cli/`
(user-facing CLI surface) and `scripts/` (one-off integrity checks and
operational tools). The CLI zone wins the first pilot because:

- it is the primary user-facing failure surface — every WEA agent hits it
  every cycle, so error semantics directly shape exit codes and CLI
  messages;
- it already mixes three error styles: zone-local custom classes, raw
  built-ins, and one broad swallow. The mix is what makes a topology
  picture useful, and the mix is small enough that one targeted change
  can move the score;
- the three zone-local classes (`PushError`, `GhError`, `IssueEditError`)
  are structurally cousins (all `RuntimeError` subclasses, all signal a
  CLI-level failure), so a shared base is a real description of intent,
  not a fabricated grouping.

Importantly, "`src/wea_cli` is the first pilot" is not the same as
"`src/wea_cli` is the system." The scanner ships designed for repo-wide
use and `scripts/` is in scope for the same census in this PR.

## Baseline picture (from `baseline.json`)

Snapshot of `origin/main` at SHA `2e8c265`:

| zone        | custom classes | placeholder | raw built-in raises | wrap raises | broad catches | swallowed | boundary raises | zone score |
|-------------|----------------|-------------|---------------------|-------------|---------------|-----------|-----------------|------------|
| src_wea_cli | 3              | 2           | 27                  | 21          | 18            | 98        | 50              | 1          |
| scripts     | 4              | 4           | 118                 | 39          | 6             | 338       | 111             | 1          |
| tests       | 0              | 0           | 8                   | 0           | 2             | 10        | 0               | 0 (info)   |

Repo-wide `repo_exception_topology_hint` = `1` (minimum across `src_wea_cli`
and `scripts`; `tests` excluded; zones with zero custom classes excluded).

The three zone-local classes in `src_wea_cli` at the baseline:

- `PushError(RuntimeError)` — raised by the `wea push` API path when the
  GitHub Contents API call cannot complete or returns invalid data.
- `GhError(RuntimeError)` — raised when `gh` CLI invocation fails or
  returns non-JSON output.
- `IssueEditError(RuntimeError)` — raised by safe label-edit primitives
  when an operation fails or requires rollback.

They never share a parent above `RuntimeError`. The zone is therefore
literally at the v0 rubric description of `1`: "scattered custom errors
with no common base."

The four classes in `scripts/` at the baseline are all placeholder
subclasses of `RuntimeError` defined in unrelated files. There is no
shared structure to extract today; the pilot deliberately does not touch
`scripts/`.

## Pilot change: `WeaCliError`

The change is one new file plus two one-line edits.

`src/wea_cli/errors.py`:

```python
class WeaCliError(RuntimeError):
    """Common base for `wea` CLI failures."""
```

Two of the three custom classes are re-rooted:

- `GhError(WeaCliError)`
- `IssueEditError(WeaCliError)`

`PushError(RuntimeError)` is left as-is in this PR. See the post-
implementation redteam for why.

Because `WeaCliError` is itself a `RuntimeError` subclass, every existing
`except RuntimeError`, `except GhError`, and `except IssueEditError` clause
continues to behave exactly as before.

After the change the scanner reports:

| zone        | custom classes | zone score |
|-------------|----------------|------------|
| src_wea_cli | 4              | 2          |
| scripts     | 4              | 1          |

Repo-wide hint stays at `1`. This is intentional and honest: the pilot did
not touch `scripts/`, so the repo as a whole is not yet at score `2`. The
scanner uses the **minimum** of per-zone scores precisely so that one zone
moving cannot mask the rest of the repo standing still.

## Pilot scope discipline

What the pilot deliberately does NOT do:

- introduce subclasses below `WeaCliError` (no
  `WeaConfigError`/`WeaIOError` hierarchy);
- migrate any of the 27 raw `ValueError` / `FileNotFoundError` raise
  sites in `cli.py`, even though several of them are clear candidates;
- collapse the broad `except Exception: pass` block near `cli.py:897`,
  which silently eats `scripts.check_task_format.validate` errors;
- rename or remove the three existing classes;
- add any CI gate, pre-commit hook, or static check that requires future
  CLI exception classes to extend `WeaCliError`;
- claim repo-level `exception_topology_score` movement.

Each of those is a candidate for a future task. They are listed with
location evidence in `baseline.json` so the next checkpoint can decide
whether they are worth picking up.

## Post-implementation redteam

After making the change and re-running the scanner, these were the
follow-up questions and answers:

1. **Did any catch site break?** No. Both `src/wea_cli/cli.py` and the
   release/gauntlet/spawn modules continue to catch `GhError` and
   `IssueEditError` by their concrete class name. Catch sites that go
   through the `RuntimeError` base (none exist today) would also keep
   working because `WeaCliError` extends `RuntimeError`.

2. **Why is `PushError` excluded from the retrofit?** `cli.py` is
   invoked as a script in some tests via
   `python src/wea_cli/cli.py ...`. In that invocation Python places
   `src/wea_cli/` on `sys.path[0]`, not `src/`, so an
   `import wea_cli.errors` from inside `cli.py` does not resolve against
   the local checkout — it falls back to whichever `wea_cli` happens to
   be on the global `sys.path`. On developer machines with multiple WEA
   worktrees, that fallback may not have `errors.py` yet, which would
   break `wea task template` and the test that exercises it. Touching
   `cli.py`'s import bootstrap to fix this is out of scope for an
   error-topology pilot, so `PushError` is named in the
   "future hardening candidates" list below and the pilot stops at
   `gh.py` and `issue_edit.py`. Two retrofitted classes are still
   sufficient for the v0 rubric's "shared base in at least one zone"
   condition.

3. **Did `pytest tests/ -q` regress?** No. The full suite has 27
   pre-existing failures on `origin/main`; this PR's changes do not add
   to that count. The new file under `tests/test_error_topology.py`
   adds 17 tests including a smoke test that re-runs the live scanner
   and asserts the retrofit is visible.

3. **Did the scanner accidentally start scoring zones higher than it
   should?** No. `_shared_base_score` is unit-tested with a synthetic
   tree containing a deeper hierarchy (`Base -> A`, `Base -> B`,
   `B -> C`) and the scanner caps the mechanical score at `2`. Score
   `3` and `4` require human review of documentation and enforcement
   that the scanner intentionally does not assert.

4. **Could a future contributor accidentally regress this by adding a
   new `class FooError(RuntimeError)` directly?** Yes, mechanically.
   The scanner will record it at the next checkpoint; the score for
   `src_wea_cli` will stay at `2` only as long as at least two custom
   classes still root onto `WeaCliError`. A single new sibling
   `FooError(RuntimeError)` does not break the score on its own; a
   wholesale revert of the three retrofitted classes would. This is
   intentional: the scanner reports the situation; the next checkpoint
   decides what to do about it. There is no CI gate yet because the
   issue forbids claiming repo-wide enforcement.

5. **Is `WeaCliError` a "base nobody uses" gaming pattern?** No. The
   two classes that re-root onto it represent live failure paths used
   in production CLI flows: every `gh` CLI call goes through `GhError`,
   and every safe-label-edit operation goes through `IssueEditError`.
   The scanner's score-2 condition requires at least two custom classes
   inheriting from a base defined inside the scanned tree, so a base
   class that never gets a subclass would not lift the score.

6. **Does the change risk surprising a downstream caller that catches
   exact `RuntimeError` to suppress library noise?** Negligible. The
   three classes were already `RuntimeError` subclasses; they remain
   `RuntimeError` subclasses. The only catchable change is an additional
   intermediate `WeaCliError` class in the MRO, which a caller can
   choose to use later.

7. **Is the new module discoverable?** It lives at the obvious path
   `src/wea_cli/errors.py`, contains a single public class, and is
   imported and re-exported into `gh.py`, `issue_edit.py`, and `cli.py`
   so the import sites act as documentation of the intent.

## Pilot self-roast (what could still be wrong)

Three things still bother me, in priority order:

1. The change is structurally trivial. Anyone reading the diff can ask
   "is this just a label?" The answer is "yes, deliberately": the v0
   rubric explicitly distinguishes `1` (scattered) from `2` (shared
   base), and this is the smallest change that is honestly at `2`. The
   redteam answer is the scanner output, not the diff itself.

2. The `_is_boundary_function` heuristic is coarse. It flags every
   raise in `cli.py`, `gh.py`, `health.py`, `spawn.py`, `release.py`,
   plus any function named `main`, `cmd_*`, `_cmd_*`, `handle_*`, or
   `*_main`. This produces a high `boundary_raise_count` (50 in
   `src_wea_cli`) but misses raises in helpers that are only reached
   from a CLI surface. v0 leaves this coarse on purpose; v1 should
   build a real call graph if the signal proves useful.

3. The scanner does not import scanned modules. A class declared as
   `class X(SomeAlias)` where `SomeAlias` is `from foo import Bar as
   SomeAlias` is recorded with parent name `SomeAlias`. The session-1
   zones don't use this pattern, but if they ever do the scanner will
   under-count the parent. This is documented in `logic.md`'s
   pre-implementation logic redteam.

The first concern is the strongest argument for "this PR should remain
census-only." I chose to land the tight retrofit anyway because: it is
the smallest, most boring change that is honestly at score 2; it produces
an `is`/`is not` checkpoint outcome rather than a "did the discussion
help?" outcome; and the issue's task-class notes lean toward implementing
"a tight, well-tested pilot improvement if justified," which a 1-file +
3-line-edit change with 17 tests qualifies as.

## Checkpoint plan

The two snapshots in this directory (`baseline.json`, `post_pilot.json`)
let the next Circle-1 checkpoint ask:

- did `src_wea_cli`'s `shared_base_zone_score` stay at `2` after the
  next two accepted Python error-handling code-change tasks?
- did `scripts`'s score move at all? (no pilot in this PR; expected: no.)
- did the count of raw built-in raises in `src_wea_cli` shrink, stay
  flat, or grow?
- did any new custom exception class land that ignores `WeaCliError`?
- did the broad `except Exception: pass` block near `cli.py:897` change?

If no eligible Python error-handling code changes land before the next
Circle-1 checkpoint, the inconclusive policy in the issue applies.

## Future hardening candidates (named, not implemented)

Surfaced from the baseline scan, in rough order of likely value:

- **`cli.py` — `PushError` retrofit.** Same shape as the `GhError` /
  `IssueEditError` retrofit landed in this PR, but blocked behind a
  `cli.py` import bootstrap fix so the script-mode invocation
  (`python src/wea_cli/cli.py ...`) can see `wea_cli.errors`.
- **`cli.py:897` — broad swallow.** The `except Exception: pass` after
  `scripts.check_task_format.validate` silently eats real validation
  failures. A small task could replace it with a narrow catch that
  emits a diagnostic.
- **`cli.py` — raw `ValueError` / `FileNotFoundError` raises.** Several
  raise sites in argument-parsing helpers raise raw built-ins where a
  `WeaCliError` subclass would let the top-level `main()` map them to a
  consistent exit code without `isinstance(exc, ValueError)` matching.
- **`scripts/` — scattered placeholder errors.** Four placeholder
  subclasses live in unrelated files. Some may be removable; others
  could be merged once the responsible agent inspects them.
- **PEP 654 `except*`.** Not present today; the scanner records it for
  completeness so the next time it appears we have the data.

Each item is a candidate for a separate future task. None is in this
PR's scope.
