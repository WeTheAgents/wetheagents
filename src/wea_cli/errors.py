"""Shared base for `wea` CLI failure types.

In this PR two of the three existing zone-local exception classes
(`GhError` in `gh.py`, `IssueEditError` in `issue_edit.py`) inherit from
`WeaCliError` instead of `RuntimeError` directly. `PushError` (in `cli.py`)
intentionally still extends `RuntimeError`; it is named in
`domains/circle-1/error_topology/wea_cli_pilot.md` as a future hardening
candidate, blocked behind a `cli.py` import-bootstrap fix that is out of
scope for an error-topology pilot.

Behavior preservation: `WeaCliError` extends `RuntimeError`, so every
existing `except RuntimeError`, `except GhError`, and `except IssueEditError`
clause keeps its prior behavior. No catch site changes, no exit codes change,
no message text changes.

This is the minimal hardening step justified by the Circle-1 error-topology
pilot. See `domains/circle-1/error_topology/wea_cli_pilot.md` for the full
pilot rationale and the pre/post-implementation redteam notes.
"""

from __future__ import annotations


class WeaCliError(RuntimeError):
    """Common base for `wea` CLI failures.

    `GhError` and `IssueEditError` inherit from this base so the
    `src/wea_cli/` zone moves from "scattered custom errors with no
    common base" (rubric score 1) to "shared base in at least one zone"
    (rubric score 2) under the Circle-1 v0 `exception_topology_score`
    rubric. `PushError` is intentionally excluded in this PR — see the
    module docstring for the reason.

    A bare `except WeaCliError` therefore catches `GhError` and
    `IssueEditError` but not `PushError`. Catch behavior for the existing
    `except GhError` / `except IssueEditError` / `except RuntimeError`
    clauses is unchanged because this base extends `RuntimeError`.
    """
