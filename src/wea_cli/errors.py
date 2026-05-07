"""Common error base for the wea CLI surface.

`WeaCliError` is the zone-local base class for user-facing wea CLI failures.
Existing subclasses (`GhError`, `PushError`, `IssueEditError`) inherit from
this base instead of `RuntimeError` directly. The base remains a `RuntimeError`
subclass, so any existing `except RuntimeError` or `except Exception` handler
continues to catch every wea CLI error without change.

Why this base exists:

- It gives the wea CLI zone a single hierarchy root for failures that should
  reach the operator with a structured message.
- It lets future code distinguish "a wea CLI failure that should print and
  exit cleanly" from "a programmer-error built-in that should reveal a bug".
- It moves the `src/wea_cli` zone's `exception_topology_score` from 1
  (scattered) to 2 (shared zone-local base), measured by
  `scripts/circle1/error_topology_census.py`.

This module intentionally has no other contents and no dependencies. It is
imported by `wea_cli.gh`, `wea_cli.issue_edit`, and `wea_cli.cli`.
"""

from __future__ import annotations


class WeaCliError(RuntimeError):
    """Base class for user-facing wea CLI failures.

    Subclass this when raising an error that should be surfaced to the
    operator with a clean message and a non-zero exit code, rather than
    propagated as a programmer-error stack trace.
    """
