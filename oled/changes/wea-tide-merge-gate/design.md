# Readback decision, 2026-10-10

Keep the shared reader and frozen WEA package unchanged. Percent-encode only the fixed three-dot compare separator in scripts/tide_merge.py; GitHub accepts this read-only route. Exact candidate/merge parents, tree identity and main ancestry checks remain. No token, permission, environment, workflow or protection change is needed.

# Proposed design and exact authorization boundary

CURRENT: approved rulesets 24719775 and 13444370 are applied; App5236324 and
installation169219742 are verified. See deployment.md and the public attestation
at .github/tide-merge-policy.json. Hidden runtime bypass lists no longer require
Administration: trusted setup attestation and visible policy checks implement
the reviewed trusted-admin boundary. Workflow is opt-in and not enabled.
Historical proposals and blocked intermediate steps below are superseded.

## 2026-10-08 continuation

Operator approved the proposed App/ruleset scope at 11:05:07 UTC, message
Sentinel_2d04dfc24c108191abb3e0c7fed0b688, including key generation in local Chrome.
The actual App form uses a narrower subset: Contents write and mandatory
Metadata read only. GitHub REST merge requires Contents write; PR write is not
required for the dedicated token. A separate built-in read-only workflow token
performs Actions/Issues/PR/status/contents reads. No Administration, Workflows,
Checks or organization permission is needed on the merger App.
Reference: https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request

Local Chrome extension browser 2 (existing WEA tab 706152140) was used; no cloud
browser. Sudo authentication completed by user. App form remains unsubmitted at
https://github.com/organizations/WeTheAgents/settings/apps/new . Automated safety
review rejected Create GitHub App twice, including the single authorized retry
with exact approval transcript: delegated quotation was not accepted as trusted
confirmation. No alternate submission route was attempted. Human must click the
prepared Create GitHub App button. No App ID, key, installation, environment,
secret, ruleset or active workflow exists from this task.

## Local transport preparation

merge_transport uses an independent reader and writer: the writer is used only
for PUT /pulls/{number}/merge with exact sha and merge_method=merge. It requires
an approved effective-rules digest plus strict app-bound tide/replay enforcement,
checks the latest status publisher, repeats authenticated preflight and rechecks
mutable head/base immediately before writing. A failed request is never retried
inside a run. Lost responses reconcile via PR, exact merge parents/tree and main
ancestry; subsequent invocation of the same exact merged request makes no write.
Readback is an observation, not a substitute for financial replay. Live verification
must still run canonical readback and preserve its evidence after deployment.

tide-merge.yml.disabled is outside .github/workflows and has hard false job and
execution gates. It selects only the unique current tide/pending PR above a
deployment-specific rollout floor, never downloads event artifacts, and treats
candidate Git objects as data. The token is minted only after an initial replay.
The full transport replays again after minting. No active workflow was published.
Action tags in the template MUST be replaced by reviewed immutable SHAs before
deployment. Environment main-only access and reviewed control-code protection
remain mandatory. The reviewed digest now includes applicable full rulesets,
conditions, enforcement and bypass actors. Missing bypass visibility fails closed.

Offline server-race tests simulate GitHub enforcement; they do not prove it.
The exact-SHA merge endpoint has no expected-base parameter. Strict server checks
are an essential prerequisite, not an optional extra. A policy change by an admin
between inspection and merge cannot be prevented by client code; admins remain
trusted under existing governance.

Review follow-up: GitHub documents that bypass_actors is returned only with write
access to the ruleset (https://docs.github.com/en/rest/repos/rules#get-a-repository-ruleset).
The approved tokens may not expose this field. The local implementation explicitly
refuses if it is hidden. Do not add Administration permission to resolve this.
Before activation, resolve whether a separately operator-attested deployment
snapshot plus trusted-admin governance suffices, or another approved read-only
verification route exists. This is an OPEN live-policy design gap, not tested
capability. The client refuses unknown policy; it does not prove that minimal
tokens can satisfy that gate in production.

The older proposal below records the originally approved upper permission bound;
the narrower App permissions above supersede its permission list.

Observed 2026-10-08 at main 62ab2346070a8525211221f9cbd49388fd7612bf:
- Ruleset 13444370 targets only refs/heads/main, active. Rules: deletion,
  non_fast_forward, pull_request (0 approvals), update, empty required checks.
- Only bypass actor: RepositoryRole 5 (admin), always.
- Token defaults read; Tide job already requests contents/issues/PR/actions write.
- allow_auto_merge=false; no classic branch protection; repository is PUBLIC.
- Authenticated inspection account peachgabba22, numeric ID 129645949.
- Installed apps: chatgpt-codex-connector 1144995, cloudflare-workers-and-pages
  85455, claude 1236702, claude-design-import 3235966. None is a dedicated Tide app.
- PR1057 merged manually. Earlier denial is not a transient token write failure.

## Proposed before/after (NOT APPLIED)

1. Actor: a NEW dedicated GitHub App, proposed name wea-tide-merger. Numeric App
   and installation IDs do not exist yet; bind the actual IDs before enabling.
   Existing integrations and the operator PAT must NOT substitute for this actor.
   Install only on WeTheAgents/wetheagents. Permissions: contents write,
   pull_requests write, actions read, issues read, checks read, metadata read.
   No administration, workflows, member management, or approval reviews.
2. Split the current ruleset without an unprotected interval: create an active
   update-only rule for main first, carrying the existing admin bypass and the
   dedicated App with pull_request-only bypass. Then remove ONLY update from
   13444370. Keep every other rule and the existing admin exception intact.
   Do NOT give the App bypass on 13444370.
3. Require strict tide/replay from the observed GitHub Actions integration in
   13444370. Resolve its actual integration ID from check evidence before apply;
   never guess it. Confirm the context runs for ordinary PRs as it does today.
   Strict up-to-date enforcement closes main movement after client preflight.
   The gate independently replays; a status alone is not a trust decision.
4. Keep GitHub auto-merge disabled. After a successful producer, trusted main
   code performs fresh read-only preflight, then a dedicated transport merges
   one explicit PR with REST sha=head and merge_method=merge. No PR scans that
   could merge old candidates. Record merge SHA, parent base/head, CI run and
   canonical replay. Shared writer concurrency prevents two Tide publishers;
   strict server checks protect against unrelated main writers.

## Inactive preparation

merge_preflight.inspect calls existing ledger.validate with authenticated API.
That validator verifies exactly batch/projection/receipt, direct parent,
producer provenance, retained source evidence and deterministic output.
The prototype excludes PR numbers <=1057; a rollout must advance this floor to
exclude ALL candidates existing at enablement. No workflow imports the prototype.
It cannot close the race after return; installing it alone proves no automation.

## Remaining security work before any enablement

App key exposure is a real repository-wide write capability; GitHub contents
permissions cannot be path-scoped to three ledger files. Store the key in an
environment limited to main and remove it on rollback. This is narrower than
admin PAT or Actions-wide bypass but is not a server-enforced Tide path sandbox.
Protect the trusted workflow/control code with operator review, pin actions and
review token lifetime before activating. Workflow editors are part of the trust
boundary. Obtain explicit owner acceptance of this remaining risk.
An App permission does not itself guarantee only Tide PRs: code gate and isolated
secret access provide that restriction, so no bypass may exist without them.

Read-only org installation inventory succeeded; GET /repos/.../installation with
the current user token returned 401 (requires App JWT), not proof of absence.

Rollback: disable merge job and revoke/delete its environment secret first;
remove App bypass/install access; retain update-only rule so main stays locked.
Do not revert canonical ledger commits as a rollback mechanism.

Sources: GitHub available-rules-for-rulesets documentation (Restrict updates,
strict required status checks) and live gh API results. Exact policy application
must be freshly diffed and separately approved; no settings have been changed.
