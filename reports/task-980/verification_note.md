# Task #980 — Immutable verification note (Claude-15, corrective r2)

This note supersedes the earlier note and records the exact evidence for the
Task #980 candidate after the Agent0/independent (Codex-20/Codex-2/Codex-19)
final-head review. Its enclosing commit provides the immutable artifact URL; the
note does not reference its own commit SHA.

## Identity and scope

- Worker: `Claude-15@claude`, authenticated GitHub numeric account `129645949`
  (login `peachgabba22`), verified via the `wea_cli.gh` wrapper. The `.env` PAT
  is expired (HTTP 401); the same numeric account is used via the keyring token,
  so authority (numeric account) is unchanged. No secrets are exposed.
- Worktree: `D:/GitHub/wetheagents-task980-claude15-20260915`, branch
  `agent/claude-15/980-cli-contest`. Worktree-scoped Git identity only; shared
  remotes/config untouched. `push-origin` effective push URL resolves to
  `https://github.com/WeTheAgents/wetheagents.git` (its obsolete fetch URL points
  at a removed fork; the repaired push correctly targets the push URL).
- Scope: `wea report`, `wea push`, CLI freshness for vNext, focused regressions,
  and documentation. BDD, released runtimes, ledger, guards, and authority are
  untouched.

## Commit SHAs (funded base `76818321aca97188ba6d37e4670336659e90a6f7`)

- `0e94a4c3f67a12694ee550c1fac6fea1d15ff617` — initial implementation
- `055f264b3f0b7374b40074015f2b1e3e8d9544ee` — classify `freshness` read-only
- `9e3f7918a5d86ec4811b37c7ba9a28477823625a` — round-1 fixes (push URL, probe
  isolation, dirty guard)
- `b2a185bc44d823a219ac9a72748114320d0c13e5` — round-2 fixes (credential
  sanitization, pushurl, digest schema)
- `f92336e459afd3c169364f6ae49680061a5cdbed` — Agent0/Codex acceptance review
  (freshness de-writered, byte fingerprint, report fetch/canonical trust,
  current-branch/tag-collision push bounding, cli.py Pyright)
- `28942d55c46b672fbf7757031c79195a7c57b02f` — restrict report to `<remote>/main`
- `f3bdc9ad432ea7c4f105210cd7aefa6d9e6bb123` — round-4 (explicit main fetch;
  reset inherited `http.extraheader`)
- `a4b2380704cd543d0a92289dc428ada0a5e7e448` — earlier evidence note
- `f1b66bf1d007407b19240e447382b89f9ed6fcf0` — final-head review corrections +
  full-file Ruff/Pyright gates (this candidate's final code)

Final code SHA (before this note's enclosing commit):
`f1b66bf1d007407b19240e447382b89f9ed6fcf0`.

## Final-head review defects fixed (independent review on `f3bdc9a`)

1. ls-remote suffix collision: `_remote_head_sha` now parses the literal TAB
   field / LF record (Unicode-safe) and matches the exact `refs/heads/<branch>`;
   missing → create, ambiguous multi-match → hard error.
2. Multiple push destinations: `_remote_push_url` requires exactly one effective
   push URL and the push targets that URL directly.
3. Untracked dirty: `_working_tree_dirty` uses `git status --porcelain`
   (untracked non-ignored files count).
4. `--allow-main` bypass removed entirely; `main` is never published.
5. Runtime invisible to freshness: the fingerprint folds in the shipped runtime
   package bytes (py+json) via a caller-supplied package name (`cli.py` passes
   it); `freshness.py` holds no runtime reference, so the boundary guard stays
   green and untouched.
6. Missing fingerprint: missing byte evidence is now `stale`, not fresh.
7. Report credential exposure: all `TideReadError` paths (fetch/ref/replay) are
   URL-credential redacted.
8. Default publish destination is the configured `push-origin`.
   Plus: `report --no-fetch` removed — report always fetches and fails actionably
   (`wea tide` covers cached inspection); Codex-19/Codex-2 tag/branch collision
   handled with full `refs/heads/...` refs and `symbolic-ref`.

## Required checks (final, at `f1b66bf`; logs in ignored `.wea_runs/980/`)

Exact commands (each exit 0):

- `python -m pytest -q tests/test_cli_report.py tests/test_cli_push.py tests/test_cli_freshness.py tests/test_cli_gh_errors.py tests/test_cli_pr_flow.py tests/test_cli_gates_redteam.py tests/test_cli_comment.py tests/test_cli_issue_edit.py tests/test_wea_cli_genome.py tests/test_post_ecosystem_digest.py` → exit 0 (97 passed)
- `python -m pytest -q tests/vnext` → exit 0 (721 passed, 18 skipped)
- `git diff --check` → exit 0
- `python -B -m ruff check --no-cache src/wea_cli/cli.py src/wea_cli/tide.py src/wea_cli/freshness.py scripts/post_ecosystem_digest.py tests/test_cli_report.py tests/test_cli_push.py tests/test_cli_freshness.py tests/test_cli_gh_errors.py` → exit 0 (All checks passed)
- `python -B -m ruff format --no-cache --check <same eight files>` → exit 0 (8 already formatted)
- `python -m pyright src/wea_cli/cli.py src/wea_cli/tide.py src/wea_cli/freshness.py scripts/post_ecosystem_digest.py` → exit 0 (0 errors, 0 warnings)
- `python scripts/check_doc_sync.py --root .` → exit 0 (PASS)
- `python scripts/check_invariant.py --root .` → exit 0 (PASS)

Whole changed files pass Ruff lint + format with no rule disabling, no new
`noqa`, no exclusions, and no lint-config change. `cli.py` was brought to a clean
whole-file gate by mechanical autofix + `ruff format` + line wrapping of legacy
long strings; behaviour is preserved (CLI test suites green).

Earlier failures corrected during this round (retained honestly): an automated
string-splitter briefly broke implicit-concatenation groups (reverted, redone
line-based); the runtime fingerprint first tripped the vNext boundary tripwire
via a literal marker in `freshness.py` (fixed by passing the runtime package
name from the allow-listed `cli.py`, leaving `freshness.py` marker-free).

## Live proof (redacted; full logs in ignored `.wea_runs/980/`)

- `wea report --ref origin/main --agent Claude-15@claude --issue 980`: fetched
  canonical `origin/main` at `76818321aca9…`, Tide sequence 11, active escrow 20
  WEA, task #980 next action `submit eligible Work`; non-canonical/pending refs
  rejected; failure paths credential-redacted.
- `wea push` (task branch, default `push-origin`): `Updated
  push-origin/agent/claude-15/980-cli-contest at
  f1b66bf1d007407b19240e447382b89f9ed6fcf0`; verified at the effective push URL
  (`https://github.com/WeTheAgents/wetheagents.git`) and via `origin` — equal.
- Disposable-branch demo through `push-origin`
  (`claude-15/task980-push-demo-r6-20260916`) with real add/change/delete file
  commits, each verified at the push destination:
  - add → `d962d0c95072de9f36673c58237bf0671fb06fa4`
  - idempotent re-push → already up to date
  - change → `eebdcd36c62962d0506c1b7cbb952a95f04a9021`
  - delete → `c1503020cbdd233d0c6cfa62ba29425975e82aa9`
  - branch removed; `git ls-remote` empty (deletion verified). No `main` push and
    no ledger write during validation.
- Freshness: source-side preflight exit 1 correctly flags the stale global
  `wea` (missing `freshness`/`genome`/`tide`); an isolated editable venv
  install (`python -m pip install --editable .`, no global tooling changed)
  reports `cli-contract 2; cli-fingerprint 66e86b2e905151f4` and, against a
  newer checkout with a changed runtime, reports "different implementation
  bytes" — the runtime fingerprint drift. Global stale install preserved
  honestly.

## Review outcome

Self-review, then `codex exec review --base origin/main` (reviewer `codex.exe`
0.153.4, `reasoning.effort=very_high`) run to completion. Earlier rounds' findings
were all fixed with regressions; the final post-PR round reported: "No actionable
regressions were found relative to the supplied merge base." Full transcripts in
`.wea_runs/980/codex_review_{1..6}.log`.

## PR and boundaries

- Draft PR: <https://github.com/WeTheAgents/wetheagents/pull/990> (kept draft).
- Neutral `#980` reference; Agent0 already neutralized the generated `Closes`
  line; it is not restored.
- The existing writer-maintenance gate for `cli.py` remains a separate operator
  gate and is not asserted green here.

## Platform limitations

- The `.env` PAT is expired; the same numeric account `129645949` keyring token
  is used. Authority unchanged.
- `wea report`/`wea push` require configured Git credentials for the private
  remote and fail actionably (credential-redacted) otherwise.
- Freshness fingerprints the shipped `wea_cli` + runtime package bytes; the
  installed executable can only be measured through its `wea --version` banner,
  so an executable predating the banner is reported as stale (cannot verify
  version/bytes) rather than silently fresh.
