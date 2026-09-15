# Codex-19 candidate: task 980

## Accepted outcome and authority

The approved revision-1 Plan is the contract. Agent0 selects one eligible result
for 20 WEA after independent review and required common-control evidence.
This candidate changes report, push, install freshness and directly affected
consumers. It does not change BDD, executors, ledger data, settlement or authority.

## Code-free logic

- Resolve the configured canonical origin branch, fetch that exact branch and
  bind the report to its verified commit. Replay through the existing ledger API.
  Return a versioned report with actual runtime stages, escrow and next actions.
  Fetch/ref/replay failure returns an error without stale data. Legacy history
  is labelled and excluded from live figures.
- Verify the current branch and clean tree. Read its exact commit and effective
  push-origin destination. New branches are permitted; existing branches require
  fast-forward ancestry. Git publishes one explicit branch ref with existing
  commit identities. Verify the destination SHA before reporting success.
- Fingerprint CLI source bytes and compare the invoked CLI with the checkout.
  A standalone source preflight probes the installed executable without a source
  PYTHONPATH. Old executables that cannot answer are diagnosed as stale.

## Scope and verification checklist

- [ ] Focused report, push, freshness and subprocess regressions.
- [ ] Required existing CLI tests and tests/vnext.
- [ ] Whole changed-file Ruff lint/format and production Pyright.
- [ ] Diff, documentation sync and invariant checks.
- [ ] Live canonical report and disposable remote add/change/delete SHA proof.
- [ ] Self-roast, draft PR, post-PR Codex review until clean.
- [ ] Immutable UTF-8 verification note; no Work declaration or merge here.

## Design boundaries

Git diagnostics are withheld because raw errors can contain token URLs.
Existing Git authentication and worktree-specific push-origin remain authoritative.
No credential or remote configuration is modified. Native Git supports SSH,
credential helpers and token-bearing configured HTTPS remotes on both platforms.
The writer guard remains unchanged; its expected rejection of existing cli.py
maintenance is an installation gate for Agent0 and the operator.

## Initial findings

The funded base is 76818321aca97188ba6d37e4670336659e90a6f7.
The original CLI had 235 Ruff findings and one Pyright error. Required whole-file
checks require formatting and minimal lint repair on that directly changed file.
The obsolete REST tree reconstruction is removed from the push command.
No competitor implementation or idea was consulted.
