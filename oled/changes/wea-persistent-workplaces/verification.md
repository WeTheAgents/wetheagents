# Verification

## v2: persistent branches and role profiles

Bindings: outcome/spec/design v2. PR #1011 remains the manual-merge checkpoint; final native verdict is retained on that PR and in the external review log.

- PW-1: local native Git rehearsal `D:/AgentRuns/wea/agent0/20260921-persistent-branches/reuse.json` passed regular and squash merge cases. Two deliveries kept branch `codex/agent0` and the same path; the second PR diff contained only second.txt. No reset or force push. This supersedes the v1 fresh-branch rehearsal as proof of the current policy.
- PW-2/3/5: prior safeguards retained; unresolved PRs, dirty state and closed-unmerged work block reuse by procedure. No automated refusal is claimed.
- PW-4/6: four allocated slots recorded locally; three worker branches reserved without dispatch. Agent0 retains the transition head until merge. No protocol, ledger, Domain record or Access changes. Historic branches are retained evidence, not extra active slots.
- PW-7: separate role files exist; the actual ignored Agent0 selector resolves shared and role sources. Workers remain unlaunched; their first-run identity/role checks are required at dispatch, not claimed completed here.
- Checks: doc-sync and diff check passed; 11 runtime-boundary tests passed. Current scope is documentation, one ignore rule and local Git/registry setup; no production runtime changes or new dependencies.
- Native v2 review round 1 found missing first-dispatch refresh, domain-selector exclusion and migration of the existing detached Circle-1 place. Added explicit reserved-branch fast-forward/zero-diff checks, verified in first-dispatch.json. Circle-1 now uses codex/agent0 with a zero diff to origin/main; its actual local selector is excluded by the repository-local info/exclude file. Both role profiles resolve WEA references through the assigned WEA checkout when used in domains. No tracked Circle-1 files changed.
- Native v2 review round 2 found legacy genome/PR-helper conflicts. The current workplace procedure now explicitly supersedes old genome paths, per-task branches and mandatory wea pr recipes. It documents gh PR publication with explicit identity/repository/head/body checks, no automatic task closure, and no private WEA evidence in public domain PRs. The existing CLI pattern was inspected; protocol/CLI code is unchanged.
- Review: independent reviewer found the active onboarding prompt still required unique task branches. Corrected that prompt to the persistent-branch and role-selection procedure. No other actionable findings. Final native review is recorded on PR #1011 and in the external v2 log.

## v1 historical evidence (branch policy superseded)

Bindings: outcome/spec/design v1. Local setup and reuse verified; [PR #1011](https://github.com/WeTheAgents/wetheagents/pull/1011) published. Final native review status is retained in the PR description and external native-review logs. Manual merge remains an operator checkpoint.

- PW-1: `D:/AgentRuns/wea/agent0/20260920-persistent-workplaces/reuse.json`, observed 2026-09-20T11:06:20Z. Two sequential fresh branches in each place passed local CLI help; environment configuration stayed identical. WEA worktree count stayed 116 and Circle-1 stayed five during reuse. Probe branches were deleted locally and original HEADs restored.
- PW-2/PW-3/PW-5: independent fresh-context review `/root/workplaces_review` found no actionable issue in ownership, dirty-state, recovery or retention instructions. The local registry records this session, assignments and evidence. All old trees were retained. Manual checks are documented; automatic refusal/concurrency enforcement is not implemented or claimed.
- PW-4: only documentation changed. Domain record, Access journal, protocol code, ledger and GitHub permissions remain unchanged. Circle-1 has no tracked changes; its place is free and detached after rehearsal.
- WEA: local `.venv` CLI help, `python scripts/check_doc_sync.py`, `python -m pytest tests/vnext/test_runtime_boundary.py -q` (11 passed), and `git diff --check` passed.
- Circle-1: `.venv` bootstrap, `python -m pytest -q` (209 passed, 15 skipped), `ruff check src tests`, and `pyright src` passed.
- Actual failures: first doc-sync check rejected the new unmapped link; adding WORKPLACES.md to MAP.md resolved it. uv could not hardlink across volumes, used copies and completed successfully. No hardlink storage saving is claimed.
- Self-review: operator-requested local workflow only; no new runtime, no task/finance behavior change, no original-checkout edits. Current entrypoints and map now reference one procedure. Archived pilot and old dispatch records retain their historical descriptions.
- Lean cut: native Git and existing package tools suffice; no custom allocator, launcher, dependency declaration or cleanup daemon. Local paths and occupancy are private and have no canonical authority. Product scope is seven documentation files including runlog; production LOC is zero.

Not included: provisioning inactive workers, Codex sidebar registration, migration of existing chats, and deletion of historical trees. These need actual dispatch or the separate retention audit. Real seven-day Access expiry remains unobserved until its endpoint.

Native review round 1 found inherited Git identity in the new Circle-1 place and missing reconciliation of old worker sessions. Added per-worktree identity setup and cross-worktree first-dispatch checks. Verified both effective Agent0 authors/committers and unchanged shared repository identities in local git-identity.json. No worker was dispatched. Native review round 2 confirmed the workplace procedure, then found an encoding regression in old runlog lines. Restored the original UTF-8 history directly from origin/main and verified byte-for-byte equality after removing this session entry. Only the new handoff remains in the runlog diff.
