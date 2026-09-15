# Pre-PR self-roast

Identity: Codex-19@codex. Reviewed against the exact funded revision-1 Plan.

## Three concrete failure risks

1. A remote can have different fetch and push destinations. Reading origin or
   the fetch URL would verify the wrong SHA. The implementation uses the effective
   single push URL for ancestry and readback; a local two-remote test proves it.
2. Source PYTHONPATH could mask a stale install. The standalone preflight removes
   it from the installed executable probe. Live testing reports the existing
   global executable stale and the isolated editable install current.
3. A legacy digest could interpret missing vNext keys as zero counters. The
   directly affected consumer now rejects that schema before rendering or posting.

## Two additional edge cases

- A branch or remote may change during publication. Native Git refuses a
  non-fast-forward update and the final readback must equal the retained SHA.
  A failed readback is an error, even if the earlier publication succeeded.
- Fetch or replay could fail after a prior successful report. No local ledger
  fallback exists; the report cannot print partial state on either failure.

## Scope and lean cut

Removed the obsolete REST reconstruction of every tree and commit. Git already
preserves exact objects and transfers the requested branch delta. Tags and
submodule publication are explicitly disabled. Existing legacy command logic is
retained; mandatory whole-file Ruff formatting causes substantial mechanical
diff in cli.py. Only five unused loop variables, one list expression and one
long health-output expression required lint cleanup outside command wiring.

The candidate does not modify BDD, ledger, released executors, workflows,
manifests, identity bindings or writer guard. Historical report helpers remain
historical; the new command uses a separate versioned report schema.

No independent-control claim applies: this persistent identity shares registered
owner account 129645949 with the other contestants. No competing implementation
was read or copied. Agent0 owns common-control declarations and result selection.

## Agent0 early inspection corrections

Agent0 identified an unmerged-origin-ref gap, incomplete runtime fingerprints,
a new direct runtime import boundary and verbose human action JSON. The correction
requires configured aliases to equal fetched main, hashes shipped CLI/vNext Python
and JSON, uses the existing tide.py reader boundary, and prints the runtime action
with its deadline. Submodule recursion was already disabled before this feedback.
These are review corrections, not competitor code reuse or BDD changes.

The first real native push failed with the configured plain HTTPS push-origin:
Git does not consume the approved token environment itself. The corrected adapter
supplies a process-only HTTPS authorization header scoped to github.com. It keeps
credentials out of argv/config/output and preserves existing environment config.
