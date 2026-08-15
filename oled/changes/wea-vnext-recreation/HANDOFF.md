# Agent0 handoff: Domain/Access external publication blocked

Status: `implementation in progress / external repository-create permission required`.

The operator accepted Outcome/Spec `1.0` and design `1.1` on 2026-08-15. The
operator explicitly rejected a narrow successor reference runtime. S-13C
financial correction remains a separate future change. WEA vNext remains
`Not live`.

## Current workspace

- WEA worktree:
  `D:\GitHub\wetheagents-codex-wea-vnext-domain-access-2026-08-03`.
- WEA branch: `codex/wea-vnext-domain-access-2026-08-03`.
- WEA base: `origin/main` at `f940070` after a clean rebase.
- External local repository: `D:\GitHub\circle-1`.
- External branch: `main`.
- External local commit:
  `c538fba593d9aae06c3f60b9721b821118d8dafb`.

## Accepted boundary

- Publish Circle-1 as a real public external Domain.
- Bind its permanent repository ID, canonical locator, and full revision in an
  immutable WEA manifest.
- Keep Access as an internal seven-day WEA right with no external permission
  effect and no early revoke, renewal, extension, suspension, or transfer.
- Keep the 67-scenario `0.8 / v0_8_0` runtime closure byte-identical.
- Keep S-13C and every ledger write outside this delivery.

## Completed evidence

- Circle-1 history was filtered from WEA without deleting the WEA snapshot.
- External ownership was split into `docs/`, `src/circle1/`, and focused tests.
- WEA adapters, target profiles, checkpoints, director operations, task-index
  work, and ledger work remain in WEA.
- External package suite: `215 passed, 9 skipped`.
- The nine skips are explicit WEA integration tests; they pass when
  `CIRCLE1_WEA_ROOT` names the current WEA worktree.
- External Ruff: clean. External Pyright: 0 errors and 0 warnings.
- Installed `circle1-score` completed a black-box WEA scan with explicit root,
  profile, target, revision, and output inputs.
- WEA Domain registry and Access focus: `20 passed`.
- WEA scenario/runtime focus: `31 passed`.
- Full WEA vNext suite: `449 passed, 18 skipped`.
- Full repository suite with the worktree `src` on `PYTHONPATH`:
  `4734 passed, 18 skipped, 11 xfailed`.
- WEA focused Ruff: clean. WEA focused Pyright: 0 errors and 0 warnings.
- Economy invariant, ledger schema, doc sync, protected runtime/ledger diff, and
  `git diff --check`: pass.

## Hard blocker

`WeTheAgents/circle-1` does not exist. GitHub rejected repository creation for
both configured identities:

- `peachgabba-mc`: organization repository creation is not permitted;
- the configured `peachgabba22` token: repository creation is not accessible.

Do not publish `domains/registry/v1.json` with a placeholder repository ID or
an unobservable revision. Do not move S-11A or S-11B into the current scenario
set before the real public binding verifies.

## Exact resume sequence

1. Have an organization owner create the empty public repository
   `WeTheAgents/circle-1`, or grant create permission to the configured
   publisher.
2. In `D:\GitHub\circle-1`, add the organization remote if needed and push
   local `main` without rewriting commit
   `c538fba593d9aae06c3f60b9721b821118d8dafb`.
3. Read the permanent repository node ID and the full public default-branch
   commit SHA from GitHub.
4. Generate and verify `domains/registry/v1.json` with those exact values.
5. Re-run the focused registry/Access tests. Then promote S-11A and S-11B to
   current, leaving only S-13C accepted-future.
6. Reconcile schema, delta, migration, scenario registry, review HTML, and this
   handoff. Run every verification gate in `tasks.md`.
7. Commit narrowly, publish the WEA PR, run Codex review until clean, and merge.
8. Start S-13C as a separate OLED change only after this PR merges.

## Historical baseline

PR `#941` merged the inactive Spec `0.9` reference runtime. It proves 67
current scenarios with `BDD alignment: 100%`. Ruleset `0.8` SHA-256 is
`2b5f396b1e5c06e9be5190c3de41a626bb905eba7fb35bb327633bcc24983128`.
Executor `v0_8_0` manifest SHA-256 is
`2aed3e4fb21a31cfbb8ed544f1974c63aba8451c95e434f5a5f5dd16e1f52c53`.
No live Tide writer, ledger namespace, migration, bootstrap, or cutover was
enabled.
