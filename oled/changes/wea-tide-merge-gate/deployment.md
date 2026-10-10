# Tide merge deployment

## Dependent-job repair, 2026-10-10

Producer37975723971 published PR1064, head11c9751f, and guard37976799339
succeeded at 2026-10-09T19:04:04Z. No following merge workflow run was observed.
The workflow was active, its trigger name matched and no branch filter was set.
GITHUB_TOKEN event suppression is a hypothesis, not a proven root cause;
the available GitHub API does not expose the missing event delivery decision.
PR1064 was merged by the operator at 2026-10-10T02:41:59Z, commit62196586.
The resulting push guard triggered merge run38017926679 with no pending candidate.

Replace the separate workflow_run consumer with a dependent job in the trusted
guard. `needs: trusted-ledger-check` and a success condition establish the job
dependency without a second event. The guard exports exact PR/base/head, and the
job refuses changed identities. A successful non-Tide guard skips merge rather
than discovering another pending PR. Rollout floor advances to1064.

The main-only environment, read-only built-in job token, App Contents-write token,
installation check, repeated authenticated replay, strict server check and shared
producer/merge concurrency remain unchanged. The lock is job-scoped: the producer
can finish after dispatching the guard before the dependent merge takes its lock.
No new permission, credential, funding dispatcher or canonical ledger change.
This repair still needs manual code merge and a separately coordinated live run;
offline tests do not establish successful App merge.

Verification: 100 tests passed across merge preflight/transport, runtime boundary,
ledger and replay; targeted Ruff and YAML dependency/permission checks passed.
Independent Codex review found no substantive issue against62196586. Negative
cases include changed head/base/main, non-Tide/foreign PRs and failed replay.

Live trial 37773567075 stopped before candidate publication: adding transport
modules under wea_vnext changed the already installed Hello World package hash.
The transport now resides in scripts/tide_merge.py and tide_merge_preflight.py,
outside the frozen WEA package. No hash validator, anchor, executor or historical
evidence is changed. Exact installed package hash matches the canonical anchor
again: 84ca1de078b891d5fecc6afc914494ea93a137ab4ad36d73f6e066dbf8442683.
Regression tests assert this compatibility. The placement fix was manually merged in PR1061. The opt-in variable is now
true; successful automatic App merge has not yet been demonstrated.

This is operator-requested unpaid maintenance, not funded Work. No persistent
Agent ID is claimed. The isolated task branch was explicitly assigned for this
security change; existing persistent workplaces and their work are untouched.

App 5236324, installation 169219742: organization WeTheAgents, selected repository
wetheagents only, Contents write and Metadata read. Key resides only in the
tide-merge environment, restricted to main. The operator created the key.

Applied rules: 24719775 contains only main update restriction, with existing admin
and merger App pull_request bypass. 13444370 retains deletion/non-fast-forward/PR
protection and now requires strict tide/replay from GitHub Actions 15368. App has
no bypass there. Full policy and visible digest are in .github/tide-merge-policy.json.

Only the operator/admin and this restricted App can update main. The App's code
accepts exactly the three ordinary Tide files; it cannot approve control-code
changes. Workflows, imported Python and configuration therefore reach main only
through operator review/manual merge under the retained update restriction.
Do not give ordinary writers another main bypass. Administrators remain trusted;
disable automation and renew attestation before policy/bypass changes. Runtime
cannot observe hidden bypass-only changes with its deliberately minimal token.

Workflow is opt-in with repository variable TIDE_MERGE_ENABLED=true. Missing or
false skips the entire environment job. The operator enabled it after the original implementation was merged. Actions are pinned to observed SHAs.
The shared wea-canonical-tide concurrency serializes producer and merge transport.
PRs <=1064 are excluded by the dependent-job repair. Candidate code is never checked out or executed.

Next checkpoint: review and manually merge the dependent-job repair, then
coordinate a safe ordinary Tide candidate and verify exact merge parents/tree
plus canonical replay. Do not duplicate the separate Task1062 funding work. No rewards, winner selection,
prototype PR merges or new funds are authorized by this test. Retain negative
preflight evidence for foreign files and failed replay. Unit race simulation is
not evidence of live GitHub enforcement.

Rollback: disable TIDE_MERGE_ENABLED; remove/revoke the environment key if needed.
Retain main update restriction. Do not revert canonical financial history.
