# Handoff: WEA vNext Block 9 cutover

Status: `GitHub-native implementation is local. Activation is not run`.

## Current contract

- Outcome `1.0`
- Spec `1.1`
- Design `1.3`
- Tasks `2.2`
- Canonical root: `WeTheAgents/wetheagents`
- Repository ID: `1171421025`
- `circle-1` is a Domain repository.

Tasks `2.2` has no hash gate. The next approval protects the first real vNext
ledger write.

## Implemented path

The repository contains one candidate workflow:

`GitHub command -> Agent0 Action -> candidate branch -> trusted guard -> manual PR merge`

The candidate workflow runs on `ubuntu-latest`. It uses `GITHUB_TOKEN`. It
does not open or merge a pull request.

The guard runs from trusted base code. It reads candidate Git objects as data.
It does not check out, import, or run candidate code.

The local transaction kernel is removed. The local epoch guard is removed.
The custom projection App is removed. Public comment and label projections
remain `DEFERRED`.

Three legacy direct-write workflows are removed. The BTC workflow is manual
and read-only. Existing guards now use GitHub-hosted runners without
`ADMIN_TOKEN`.

## Local proof

- The complete vNext suite reported `596 passed, 18 skipped`.
- The final GitHub-native trust-boundary suite reported `19 passed`.
- The affected CLI and legacy-writer suite reported `38 passed`.
- Ruff passed for the changed Block 9 code and tests.
- Pyright reported `0 errors, 0 warnings` for `src/wea_vnext/block9`.
- The ledger invariant passed: `19025 = 10000 + 9025`.
- The ledger schema check passed.
- All 15 tracked workflow files parsed as YAML.

## Open finding

GitHub Issue `#1` remains open. It is also the only task with `open` status in
`ledger/task_index.json`.

The activation snapshot must resolve this mismatch. Use one of these actions:

1. Close Issue `#1` before the frozen snapshot.
2. Keep it open in GitHub and give it one `historical-close` outcome in the
   activation package.

The second action preserves the current Issue state. It also makes the cutover
decision explicit. It is the current recommendation.

## Next action

1. Finish the code review.
2. Merge the code-only implementation without `ledger/vnext/**` data.
3. Read the resulting canonical `main` commit.
4. Build one exact activation package from that commit.
5. Run the no-write rehearsal.
6. Show the exact files and hashes to the operator.
7. Stop before the Agent0 workflow starts.

Do not change GitHub settings, repository visibility, or canonical ledger data
before that approval.

Worktree:
`D:/GitHub/wetheagents-codex-wea-vnext-sdd-review-2026-08-16`

Branch:
`codex/wea-vnext-block9-code-2026-08-22`
