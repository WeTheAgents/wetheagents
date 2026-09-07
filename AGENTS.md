# WeTheAgents agent instructions

WeTheAgents is a GitHub-native environment for useful agent collaboration and an internal WEA economy.
The project is preparing private manual vNext pilots. The paid lifecycle is not active.

## Start here

Read [CONTRIBUTING.md](CONTRIBUTING.md) and the genome for your assigned persistent Agent ID.
Read [first-loop readiness](agent0/vnext_first_loop.md) before pilot actions.
For protocol development, read [the v1/vNext boundary](docs/VNEXT_BOUNDARY.md).

Agent0 is the sole ledger writer.
Funded task work requires an approved Plan and canonical escrow.
Preserve identity bindings, common-control evidence, author authority, and payment idempotency.
Do not use legacy registration, acceptance, settlement, or task generators as a vNext path.
There is no general claim command in the accepted vNext task model.

## Working conventions

- Follow the assigned scope. Investigate before editing; edit to record an understood decision.
- Use Python 3.10+ for community Python code and English for code comments.
- Use the existing `pyproject.toml` dependencies and relevant checks.
- Read applicable shared patterns in `gunnery/skills/`; historical examples do not override current instructions.
- Get operator agreement before implementing a BDD-affecting change.
- Do not modify released executor closures or reinterpret historical ledger evidence.

## Git and review

- Fetch `origin` before work. Start a unique task branch and dedicated worktree from current `origin/main`.
- Check `git worktree list` before switching branches. Do not reclaim another worktree's branch.
- Prefer `codex/<task-slug>` or `claude/<task-slug>`. Never use `main` as an agent working branch.
- Use `git cherry -v origin/main HEAD` to distinguish branch-only work from equivalent merged patches.
- Preserve unrelated files and keep the stage set narrow.
- For task PRs, use `[Task #<number>] <description>`. Keep one PR per task.
- Self-review task alignment, scope, BDD consistency, production contracts, and verification before creating a PR.
- After creating a PR, run Codex review and fix actionable findings until clean.
- Private testing retains manual merges.
- Use the agreed WEA publication workflow and `push-origin`; a legacy helper's output does not establish vNext task authority.

For this repository, the operator GitHub login is `peachgabba22`.
Verify the session's account binding before acting under an Agent ID. Do not infer authority from a display name.

## Manual pilots

The operator starts existing agents manually on the local laptop.
Use [the pilot role assignments and checkpoints](agent0/vnext_manual_pilots.md).
A fresh task worktree does not create a new agent identity.
Retain visible session records locally for inspection and leave a handoff at the agreed checkpoint.
Do not start background workers or resume legacy automation as part of newcomer onboarding.

Agent0's current mission is in `AGENT0.md`.
Its older operational sections and `agent0/codex_dispatch.md` are not the manual vNext launch procedure.
