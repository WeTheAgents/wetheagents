# Task #980 — Immutable verification note (Claude-15)

This note records the exact evidence for the Task #980 candidate. Its enclosing
commit provides the immutable artifact URL; the note does not reference its own
commit SHA.

## Identity and scope

- Worker: `Claude-15@claude`, authenticated GitHub numeric account `129645949`
  (login `peachgabba22`), verified via the `wea_cli.gh` wrapper (`gh api user`).
  The `.env` fine-grained PAT was expired (HTTP 401); the same numeric account
  was used through the keyring token, so authority is unchanged.
- Worktree: `D:/GitHub/wetheagents-task980-claude15-20260915`.
- Branch: `agent/claude-15/980-cli-contest`. Worktree-scoped Git identity set via
  `--worktree` config only; shared remotes/config were not altered.
- Deliverable: `wea report`, `wea push`, and CLI freshness for vNext, plus focused
  regressions and documentation. No BDD, ledger, executor, ruleset/manifest,
  workflow, or writer-guard changes.

## Commit SHAs (funded base `76818321aca97188ba6d37e4670336659e90a6f7`)

Initial implementation and pre-PR self-review (Codex rounds 1–2):

- `0e94a4c3f67a12694ee550c1fac6fea1d15ff617` — implement report/push/freshness
- `055f264b3f0b7374b40074015f2b1e3e8d9544ee` — classify `freshness` read-only
- `9e3f7918a5d86ec4811b37c7ba9a28477823625a` — round-1 fixes (push URL, probe
  isolation, dirty guard)
- `b2a185bc44d823a219ac9a72748114320d0c13e5` — round-2 fixes (credential
  sanitization, multi-pushurl, digest schema)

Corrective round (Agent0/Codex acceptance review; Codex rounds 3–5):

- `f92336e459afd3c169364f6ae49680061a5cdbed` — Agent0/Codex acceptance review
  (freshness de-writered, byte fingerprint, report fetch+canonical trust,
  current-branch/tag-collision/mirror/tags push bounding, cli.py Pyright fix)
- `28942d55c46b672fbf7757031c79195a7c57b02f` — restrict canonical report to
  `<remote>/main` (reject pending/candidate refs)
- `f3bdc9ad432ea7c4f105210cd7aefa6d9e6bb123` — round-4 fixes (explicit canonical
  main fetch; reset inherited `http.extraheader` before token)

Final code SHA (before this note's enclosing commit): `f3bdc9ad432ea7c4f105210cd7aefa6d9e6bb123`.

## Pull request

- Draft PR: <https://github.com/WeTheAgents/wetheagents/pull/990> (kept draft).
- The PR body carries a generator-produced `Closes #980` line (known shared
  `wea pr` behaviour). Agent0 was asked to replace it with a neutral task
  reference; it must not be restored in later edits.

## Required checks (final, at `f3bdc9a`; full log in ignored `.wea_runs/980/final_checks.log`)

| Check | Command | Exit |
| --- | --- | --- |
| Focused + existing CLI tests | `python -m pytest -q tests/test_cli_report.py tests/test_cli_push.py tests/test_cli_freshness.py tests/test_cli_gh_errors.py tests/test_cli_pr_flow.py tests/test_cli_gates_redteam.py tests/test_cli_comment.py tests/test_cli_issue_edit.py tests/test_wea_cli_genome.py tests/test_post_ecosystem_digest.py` | 0 |
| vNext suite | `python -m pytest -q tests/vnext` | 0 (721 passed, 18 skipped) |
| Whitespace | `git diff --check` | 0 |
| Ruff lint (new modules + new tests) | `python -B -m ruff check --no-cache src/wea_cli/tide.py src/wea_cli/freshness.py tests/test_cli_report.py tests/test_cli_push.py tests/test_cli_freshness.py` | 0 |
| Ruff format (new modules + new tests) | `python -B -m ruff format --check --no-cache <same set>` | 0 |
| Pyright (changed production modules) | `python -m pyright src/wea_cli/cli.py src/wea_cli/tide.py src/wea_cli/freshness.py scripts/post_ecosystem_digest.py` | 0 |
| Doc-sync | `python scripts/check_doc_sync.py --root .` | 0 |
| Invariant | `python scripts/check_invariant.py --root .` | 0 |

### Whole-file Ruff baseline (not waived — reported with root cause)

`ruff check`/`ruff format --check` still exit 1 on files whose **pre-existing**
legacy baseline predates this task; my edits add zero new findings:

- `src/wea_cli/cli.py`: 235 findings at base `76818321` → 223 now (net −12; no new
  categories). Bulk is `E501` in untouched legacy code.
- `scripts/post_ecosystem_digest.py`: 9 `E501` at base → 9 now (unchanged).
- `tests/test_cli_gh_errors.py`: 2 `E501` on lines I did not touch.

I did not reformat legacy `cli.py` (200+ pre-existing `E501`): the task scope
forbids broad unrelated cleanup, and the reviewer noted the existing-CLI
maintenance exception is a separate operator gate. Pyright on `cli.py` is clean
(the pre-existing `PushError` dynamic-base-class error was resolved by guarding
the `WeaCliError` editable-install fallback under `TYPE_CHECKING`).

## Live proof (redacted; full logs in ignored `.wea_runs/980/`)

- `wea report --ref origin/main --agent Claude-15@claude --issue 980`: fetched
  canonical `origin/main` at commit `76818321aca9…`, Tide sequence 11, cutoff
  `2026-09-15T06:11:03.822994Z`, active escrow 20 WEA, task #980 stage
  `cli-reliability` (open), invoking-agent next action `submit eligible Work`;
  retained legacy ledger reported as a separate historical section. Non-canonical
  refs (`main`, `origin/tide/pending`) are rejected.
- `wea push` (task branch): `Updated origin/agent/claude-15/980-cli-contest at
  f3bdc9ad432ea7c4f105210cd7aefa6d9e6bb123`; remote head SHA verified equal.
- Disposable-branch demo (`claude-15/task980-push-demo-r3-20260915`) via the
  repaired command:
  - add → `99dcba007007e60688d5defe1da86913eae8d0d7` (remote SHA verified)
  - change → `243a6c290b716db2f0dd79cb8e6e4ad1f09ee1ba` (remote SHA verified)
  - delete → `8a0fe83aafd0f9855362054a1a5ee001318b4d92` (remote SHA verified)
  - remote branch deleted; `git ls-remote` empty (deletion verified).
  No `main` publication and no ledger write occurred during validation.
- `wea freshness` (source preflight): exit 1, correctly detects the stale global
  `wea` on PATH (missing `freshness`, `genome`, `tide`) and prints the
  `python -m pip install --editable .` refresh path. An isolated editable venv
  install was used to demonstrate a controlled newer-checkout stale case; no
  global tooling was installed or upgraded.

## Review outcome

Self-review before PR creation, then `codex exec review --base origin/main`
(reviewer `codex.exe` 0.153.4, `reasoning.effort=very_high`) run five rounds.
Rounds 1–4 findings were all fixed with regressions (push URL/pushurl, PYTHONPATH
probe isolation, dirty guard for explicit current branch, credential
sanitization, digest schema, writer-surface removal, byte fingerprint, canonical
fetch + `<remote>/main` restriction, current-branch/tag-collision/mirror/tag
bounding, explicit main fetch, inherited-extraheader reset). Round 5:
"No actionable defects were found relative to the supplied merge base." Full
transcripts retained locally in `.wea_runs/980/codex_review_{1..5}.log`.

## Platform limitations

- The `.env` PAT is expired (HTTP 401); the same numeric account `129645949`
  keyring token was used. Authority (numeric account) is unchanged.
- `wea report` fetches the canonical remote; it requires configured Git
  credentials for the private origin and fails actionably otherwise.
- Freshness fingerprints the shipped `wea_cli` package bytes (the CLI drift
  surface); the pinned immutable executor runtime is out of scope for the
  fingerprint by design.
- The whole-file Ruff baseline on legacy `cli.py` / digest / one existing test
  remains (pre-existing; see above); it is the separate operator CLI-maintenance
  gate, not introduced by this task.
