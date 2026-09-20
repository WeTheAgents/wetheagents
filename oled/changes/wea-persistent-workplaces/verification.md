# Verification

Bindings: outcome/spec/design v1. Local setup and reuse verified; PR #1011 published; native review fixes awaiting re-review. Manual merge remains an operator checkpoint.

- PW-1: `D:/AgentRuns/wea/agent0/20260920-persistent-workplaces/reuse.json`, observed 2026-09-20T11:06:20Z. Two sequential fresh branches in each place passed local CLI help; environment configuration stayed identical. WEA worktree count stayed 116 and Circle-1 stayed five during reuse. Probe branches were deleted locally and original HEADs restored.
- PW-2/PW-3/PW-5: independent fresh-context review `/root/workplaces_review` found no actionable issue in ownership, dirty-state, recovery or retention instructions. The local registry records this session, assignments and evidence. All old trees were retained. Manual checks are documented; automatic refusal/concurrency enforcement is not implemented or claimed.
- PW-4: only documentation changed. Domain record, Access journal, protocol code, ledger and GitHub permissions remain unchanged. Circle-1 has no tracked changes; its place is free and detached after rehearsal.
- WEA: local `.venv` CLI help, `python scripts/check_doc_sync.py`, `python -m pytest tests/vnext/test_runtime_boundary.py -q` (11 passed), and `git diff --check` passed.
- Circle-1: `.venv` bootstrap, `python -m pytest -q` (209 passed, 15 skipped), `ruff check src tests`, and `pyright src` passed.
- Actual failures: first doc-sync check rejected the new unmapped link; adding WORKPLACES.md to MAP.md resolved it. uv could not hardlink across volumes, used copies and completed successfully. No hardlink storage saving is claimed.
- Self-review: operator-requested local workflow only; no new runtime, no task/finance behavior change, no original-checkout edits. Current entrypoints and map now reference one procedure. Archived pilot and old dispatch records retain their historical descriptions.
- Lean cut: native Git and existing package tools suffice; no custom allocator, launcher, dependency declaration or cleanup daemon. Local paths and occupancy are private and have no canonical authority. Product scope is seven documentation files including runlog; production LOC is zero.

Not included: provisioning inactive workers, Codex sidebar registration, migration of existing chats, and deletion of historical trees. These need actual dispatch or the separate retention audit. Real seven-day Access expiry remains unobserved until its endpoint.

Native review round 1 found inherited Git identity in the new Circle-1 place and missing reconciliation of old worker sessions. Added per-worktree identity setup and cross-worktree first-dispatch checks. Verified both effective Agent0 authors/committers and unchanged shared repository identities in local git-identity.json. No worker was dispatched. Re-review pending.
