# Tide merge deployment

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
false skips the entire environment job. Default is disabled until operator merges
this reviewed implementation and enables it. Actions are pinned to observed SHAs.
The shared wea-canonical-tide concurrency serializes producer and merge transport.
PRs <=1059 are excluded. Candidate code is never checked out or executed.

Next checkpoint: review the code PR, merge it manually, enable the variable,
publish a fresh ordinary Tide batch including existing Work1058/1059 and verify
exact merge parents/tree plus canonical replay. No rewards, winner selection,
prototype PR merges or new funds are authorized by this test. Retain negative
preflight evidence for foreign files and failed replay. Unit race simulation is
not evidence of live GitHub enforcement.

Rollback: disable TIDE_MERGE_ENABLED; remove/revoke the environment key if needed.
Retain main update restriction. Do not revert canonical financial history.
