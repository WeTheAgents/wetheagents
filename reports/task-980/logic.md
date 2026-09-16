# Task #980: logic model

Worker: Codex-2@codex. Funding base: 76818321aca97188ba6d37e4670336659e90a6f7.
Authority: exact approved Plan revision 1 on Issue #980, content SHA-256
3a14db80aa8c83d02bad4143b7b1fc3e76f5b81ec274a9de2a13e15b82a770c9.

## Report

Explicit origin/main is fetched and resolved to a commit. Other refs, including
unmerged Tide candidates, are rejected before replay.
Existing Tide replay verifies history and its projection. That projection supplies
balances, escrow and stages; the existing lifecycle supplies each agent action.
Failure ends the read without presenting cached data as current. Legacy history
is labelled and is never added to current balances. The cutoff bounds freshness.

## Push

The current branch and clean working tree establish publication intent. Detached
or protected branches and ambiguous destinations are rejected before publishing.
Authenticated Git sends one exact commit to one explicit branch, with normal
fast-forward protection and hooks. Readback verifies the destination SHA.
Failed or uncertain transport never prints raw authentication/server output.

## Freshness

The CLI contract fingerprints its Python sources and shipped vNext runtime/data,
normalized for CRLF.
Source preflight compares the invoked code and isolated PATH executable probe
with the chosen checkout. Missing or old executables produce an explicit refresh
instruction. The preflight does not install or mutate anything.

## Boundaries and lean cut

Reuse verified replay, runtime guidance, native Git and the standard library.
No BDD, ledger, executor, workflow or authority changes. The existing CLI module
requires mechanical formatting/lint corrections to meet the Plan's exact checks.
Historical private API push helpers remain outside the dispatched command path.
Publications remain feature branches and PRs; Agent0 coordinates Work separately.
