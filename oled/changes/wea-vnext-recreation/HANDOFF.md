# Agent0 handoff: Domain/Access review pending

Status: `implementation verified / independent PR review pending`.

The operator accepted Outcome/Spec `1.0` and design `1.1` on 2026-08-15. The
operator explicitly rejected a narrow successor reference runtime. S-13C
financial correction remains a separate future change. WEA vNext remains
`Not live`.

## Current workspace

- WEA worktree:
  `D:\GitHub\wetheagents-codex-wea-vnext-domain-access-2026-08-03`.
- WEA branch: `codex/wea-vnext-domain-access-2026-08-03`.
- WEA base: `origin/main` at `882a063` after a clean rebase.
- External local repository: `D:\GitHub\circle-1`.
- External branch: `main`.
- External public repository: `https://github.com/WeTheAgents/circle-1`.
- External permanent repository ID: `R_kgDOT4-F-Q`.
- External verified revision:
  `36a71440840351aa462e61a8ad5955881f55ecb0`.

## Accepted boundary

- Publish Circle-1 as a real public external Domain.
- Bind its permanent repository ID, canonical locator, and full revision in an
  immutable WEA manifest.
- Keep Access as an internal seven-day WEA right with no external permission
  effect and no early revoke, renewal, extension, suspension, or transfer.
- Keep the 67-scenario `0.8 / v0_8_0` runtime closure byte-identical while
  adding S-11A and S-11B as current control-plane scenarios.
- Keep S-13C and every ledger write outside this delivery.

## Completed evidence

- Circle-1 history was filtered from WEA without deleting the WEA snapshot.
- The public repository exposes the verified revision above on `main`; GitHub
  CI run `31866669759` is green.
- External ownership was split into `docs/`, `src/circle1/`, and focused tests.
- WEA adapters, target profiles, checkpoints, director operations, task-index
  work, and ledger work remain in WEA.
- External package suite: `215 passed, 9 skipped`.
- The nine skips are explicit WEA integration tests; they pass when
  `CIRCLE1_WEA_ROOT` names the current WEA worktree.
- External Ruff: clean. External Pyright: 0 errors and 0 warnings.
- Installed `circle1-score` completed a black-box WEA scan with explicit root,
  profile, target, revision, and output inputs.
- The canonical `domains/registry/v1.json` binds the permanent repository ID,
  canonical locator, exact revision, record hash, and registry hash.
- WEA Domain registry and Access focus: `28 passed`.
- WEA scenario/runtime focus: `39 passed`.
- The current scenario registry contains exactly 69 current scenarios and one
  accepted-future scenario. `BDD alignment: 100%`.
- Full WEA vNext suite: `457 passed, 18 skipped`.
- Full repository suite with the worktree `src` on `PYTHONPATH`:
  `4742 passed, 18 skipped, 11 xfailed`.
- WEA Ruff: clean. WEA Pyright: 0 errors and 0 warnings.
- Economy invariant, ledger schema, task-index schema, doc sync, protected
  runtime/ledger diff, and `git diff --check`: pass.

## Remaining gate

There is no product, design, or identity blocker. PR `#942` is open. Review
passes 2–4 found seven fail-closed contract defects. Pass 4 required one active
verified authority binding and delayed expiry evaluation. Focused regressions
now prove both boundaries. The remaining gates are final independent review, PR
checks, and merge. Do not add S-13C, a successor runtime, live Tide, ledger
writes, bootstrap, migration, or GitHub permission operations to this PR.

## Exact resume sequence

1. Publish the pass-4 fixes and repeat independent review on the exact branch.
2. Mark PR `#942` ready and merge after CI passes.
3. Start S-13C as a separate OLED change and PR only after this PR merges.

## Historical baseline

PR `#941` merged the inactive Spec `0.9` reference runtime. It proves 67
current scenarios with `BDD alignment: 100%`. Ruleset `0.8` SHA-256 is
`2b5f396b1e5c06e9be5190c3de41a626bb905eba7fb35bb327633bcc24983128`.
Executor `v0_8_0` manifest SHA-256 is
`2aed3e4fb21a31cfbb8ed544f1974c63aba8451c95e434f5a5f5dd16e1f52c53`.
No live Tide writer, ledger namespace, migration, bootstrap, or cutover was
enabled.
