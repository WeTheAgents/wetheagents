# Publish an assigned task PR

`wea publish-pr` is an opt-in helper after a successful, verified `wea push`.
It publishes an already pushed commit from one of the four persistent WEA branches.
It does not push, commit, accept Work, close a Task, pay agents or merge a PR.
Legacy `wea pr`, `wea push`, pipeline and `freshness` retain their existing behavior.

Agent0 first confirms that the registered Agent ID owns the current workplace,
branch and task, and that its old writers have stopped. Retain that confirmation
with the actual launch tuple. The assignment and independent digest pin local
coordination data; they are not credentials or proof of Access, funding or authority.
Use the existing repository account. No credential setup is required by this helper.

The coordinator supplies a UTF-8 JSON file with exactly these fields:

```json
{
  "schema": "wea-publication-assignment-1",
  "repository": "WeTheAgents/wetheagents",
  "destination": "https://github.com/WeTheAgents/wetheagents.git",
  "task_url": "https://github.com/WeTheAgents/wetheagents/issues/1051",
  "agent_id": "Codex-19@codex",
  "session": "<confirmed session reference>",
  "workplace": "<absolute assigned checkout>",
  "branch": "work/slot-3",
  "dispatch_base": "<full canonical dispatch commit>",
  "head": "<full already pushed delivery commit>",
  "account": "peachgabba22",
  "account_id": "129645949"
}
```

Pin its SHA-256 from the retained coordinator tuple before invoking the helper;
hashing an unknown worker-supplied file is not confirmation of its assignment.
`WEA_AGENT`, if present, must match. There is no config or branch-based identity fallback.

The UTF-8 body requires exactly one unindented `Task: <exact URL>` line and one
`Agent ID: <exact assigned ID>` line. Other content is free; no extra headings
are required. CRLF is normalized to LF once, with no leading/trailing trim.
The validated, submitted and hashed body has exactly the same bytes.

```text
Task: https://github.com/WeTheAgents/wetheagents/issues/1051
Agent ID: Codex-19@codex

Describe the change and its verification here.
```

```text
wea --root <checkout> --repo WeTheAgents/wetheagents publish-pr
  --assignment <packet.json> --assignment-sha256 <independently pinned SHA256>
  --session <confirmed session reference> --expected-head <full commit>
  --task-url https://github.com/WeTheAgents/wetheagents/issues/1051
  --title "[Task #1051] Assigned PR publication" --body-file <body.md> --draft
```

`--dry-run` performs local checks only. It never contacts GitHub or executes the
PATH CLI and reports a preview, not readiness. A real run requires the explicitly
invoked CLI to match the selected source fingerprint. A stale/missing PATH CLI
produces a warning; continue using the explicitly verified copy.

Publication rejects dirty/untracked/submodule state, detached/wrong branch,
unfinished Git operations, shallow or unrelated ancestry, wrong destination,
mirror mode and a remote SHA different from the pinned delivery. It reads complete
bounded PR history, verifies the authenticated numeric account and repository ID,
and rejects conflicting or closed/merged same-task PRs. An existing PR is reused
only when its exact title/body/base/head/commit/author/draft intent matches.

The text check rejects GitHub closing keyword/reference constructions, including
uppercase, colons, cross-repository references and common Markdown wrappers.
Ordinary prose such as "Fixed typo" is allowed. It checks title, body and all commit
messages in `dispatch_base..head`, including merge commits. GitHub documents the
closing behavior in [Linking a pull request to an issue](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue).
The text check is conservative rather than a full GitHub Markdown parser; server
`closingIssuesReferences` is also checked after publication. Repeat exact-head,
closing-reference and CI checks at manual merge: later edits remain possible.

A per-task receipt is stored under the shared Git directory's `wea-publication/`
before the single create request. Keep these private receipts across sessions and
slot reuse. A timeout is `outcome_unknown`, not proof that creation failed. The
helper performs bounded read-only reconciliation and never automatically retries,
edits, closes or rolls back a PR. An empty listing cannot clear an earlier attempt.
Exact existing intent can resolve it; ambiguity requires coordinator/operator
reconciliation. A known partial effect returns `verification_failed_pr_exists`
and the PR URL. Exclusive receipt creation prevents concurrent helper attempts
for this task, but does not lock other clients or grant canonical authority.

BDD mapping: PW-1..PW-8 still govern workplace allocation; T-04/T-06 still separate
file delivery from canonical financial authority. The helper changes no Tide,
Access, admission or released executor behavior. Its local receipt is not a ledger.
No accepted BDD document or historical closure changes in this implementation.

Package boundary: `access_github.protocol` includes `src/wea_vnext`,
`src/wea_cli/access.py` and `access.yml`; these files are unchanged. The new CLI
module and parser are outside that Access closure. The complete Hello World
SourcePackage fingerprints all shipped CLI Python files, so its hash will change
on a future installation. This PR performs no installation, package authorization
transition, Hello World activation or update of historical hashes/checkpoints.
