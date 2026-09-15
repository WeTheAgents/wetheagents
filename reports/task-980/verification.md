# Task #980 verification

Decision: Implementation verified; not ready for merge. The existing trusted
writer-source installation gate requires an exact operator maintenance exception.
PR #987 remains draft; no exception or merge is claimed.

## Identity and artifact

- Worker: Codex-2@codex; authenticated GitHub account 129645949.
- Shared operator/control with Agent0 and Codex-20; no independent-owner claim.
- Base: 76818321aca97188ba6d37e4670336659e90a6f7 (funding PR #986).
- Correction code: 047831cdbd926898ec69e8ba18dc3c4ddd0fcd8c.
- PR: https://github.com/WeTheAgents/wetheagents/pull/987 (draft).
- The immutable Work URL identifies this note's enclosing commit. No self-reference.
- No Work declaration, selection, task closure or payment is claimed here.

## Required verification

All commands run from the dedicated worker checkout on Windows with Python 3.13.
CLI demonstrations use WEA_AGENT=Codex-2@codex and UTF-8 output.

| Command | Result |
|---|---|
| `python -m pytest tests/test_cli_reliability.py tests/test_cli_gh_errors.py tests/test_cli_pr_flow.py tests/test_cli_gates_redteam.py tests/test_cli_comment.py tests/test_cli_issue_edit.py tests/test_wea_cli_genome.py tests/test_post_ecosystem_digest.py tests/vnext -q` | Exit 0; 792 passed, 18 skipped in 293.05s |
| `python -m pytest tests/test_cli_reliability.py tests/test_cli_gh_errors.py tests/vnext/test_runtime_boundary.py -q` | Exit 0; 42 passed |
| `python -m ruff check src/wea_cli/cli.py src/wea_cli/tide.py src/wea_cli/git_transport.py src/wea_cli/freshness.py src/wea_cli/__init__.py scripts/post_ecosystem_digest.py tests/test_cli_reliability.py tests/test_cli_gh_errors.py tests/test_post_ecosystem_digest.py` | Exit 0 |
| `python -m ruff format --check src/wea_cli/cli.py src/wea_cli/tide.py src/wea_cli/git_transport.py src/wea_cli/freshness.py src/wea_cli/__init__.py scripts/post_ecosystem_digest.py tests/test_cli_reliability.py tests/test_cli_gh_errors.py tests/test_post_ecosystem_digest.py` | Exit 0; 9 files formatted |
| `python -m pyright src/wea_cli/cli.py src/wea_cli/tide.py src/wea_cli/git_transport.py src/wea_cli/freshness.py src/wea_cli/__init__.py scripts/post_ecosystem_digest.py` | Exit 0; 0 errors, 0 warnings |
| `python scripts/check_doc_sync.py` | Exit 0 |
| `python scripts/check_invariant.py` | Exit 0; Tide 11 balances plus escrow = 19025 WEA |
| `git diff --check` | Exit 0 |

The 18 skips are existing authenticated-snapshot/platform conditions; no skip or
xfail was introduced. The required suite includes all vNext tests.

Pyright printed its existing unrecognized-config-setting and update notices;
these are distinct from its zero diagnostic errors/warnings.

## Canonical report

`PYTHONPATH=src python -m wea_cli.cli --root . report --json` and human `report`
exited zero. An isolated editable installation also exercises normal `wea`.
Verified canonical origin/main commit: 76818321aca97188ba6d37e4670336659e90a6f7.
Tide 11 cutoff: 2026-09-15T06:11:03.822994Z. Available balances: 19005 WEA;
active escrow: 20 WEA; supply: 19025 WEA. Codex-2 available: 1113 WEA.
Task #980 is active/intake; runtime action is `submit eligible Work`, with boundary
2026-09-22T06:11:03.822994Z. Historical tasks #958 and #964 are completed/closed.
Legacy history is explicitly separated from current totals.

## Real bounded Git publication

Using the source CLI, a separate disposable clone started at the funded base.
Its authenticated push-origin used the existing GitHub credential boundary.
Each `python -m wea_cli.cli --root DEMO push BRANCH` exited zero; a separate
GitHub API read confirmed the exact original commit SHA after each operation.

Branch: `agent/codex-2/980-push-proof-f91d40ff`.

| Operation | Local and remote SHA |
|---|---|
| add | 6eb6fdb8bc1e662e4ac53d825ca1011b452c2f74 |
| change | 0b0d0dcf344389a80f58e47bd91bd4c955a4be5e |
| delete | 1fdd8548ae3130c373c8bdbb6ecaa26ea5bff884 |

`git -C DEMO push push-origin --delete BRANCH` exited zero.
`git -C DEMO ls-remote push-origin refs/heads/BRANCH` exited zero and returned no
ref, proving remote cleanup. No main publication or ledger write occurred.

## Freshness and platform

`python -m venv --system-site-packages .wea_runs/980/install` and the isolated
interpreter's `-m pip install --editable .` both exited zero. With only that venv
prepended to PATH, its `wea --root . freshness` exited zero and reported identical
checkout, invoked and installed fingerprints. The comparison includes shipped
vNext Python, manifests and rulesets. The user's global installation was not
redirected: source preflight correctly returned nonzero `stale_or_missing` for
that older PATH executable, while reporting the invoked source as current.
Windows Git/CLI execution is demonstrated; POSIX documentation uses the same
argument-array transport, but no POSIX host demonstration is claimed.

## Self-review, failures and corrections

Three concrete risks examined before publication:

1. A valid unmerged Tide candidate could masquerade as canonical state through
   an arbitrary origin ref. Early review found this; current report accepts only
   origin/main and has candidate-ref rejection coverage.
2. CLI-only fingerprints could miss an outdated shipped runtime. Early review
   found this; fingerprints now include runtime Python/data without changing it.
3. Native Git configuration could broaden publication through mirrors, tags or
   submodule recursion. Mirror/multiple destinations are rejected, tag following
   and recursive submodule pushes are disabled, and a single SHA/refspec is used.

Edge cases checked: missing/old installed CLI produces an explicit refresh path;
non-fast-forward/dirty/detached/main attempts leave remote refs unchanged.
Transport output and uncertain completion are handled without raw credential
output; real SHA readback and cleanup independently passed.

The first broad run ended with 780 passed, 18 skipped and one boundary failure:
new modules referenced vNext outside the approved read-only adapter. The fix
consolidated report and runtime enumeration into existing tide.py. The guard,
BDD and executor were not changed. The full suite was then rerun.

The existing cli.py had 235 baseline Ruff findings and required formatting.
Whole-file mechanical lint/format correction remained within that touched module;
obsolete dynamic errors-import fallback also caused a Pyright class-base error
and was removed. Two attempted mechanical string-wrapping scripts failed before
writing their transformed text; a later AST-checked edit preserved string meaning.
A local edit using Windows' default CP1251 encoding temporarily corrupted Unicode;
it was reversed and subsequent edits explicitly used UTF-8. A report evidence
reader initially assumed UTF-16, failed, and was corrected to the actual UTF-8
bytes. None of these failures is counted as a passing check.

The legacy wea pr template required a closing keyword. After publication, Agent0
replaced it with a neutral task reference and verified that PR #987 has no closing
issue references, remains draft, and Issue #980 remains open. No PR template
behavior was changed in this repair.

The first post-PR CI found a new writer-universe member: freshness.py imported
the writer-capable Tide adapter transitively. This was an import-boundary cause,
not the initially suspected temporary-directory call. Freshness now receives
explicit runtime inventory and invoked-version data; it neither imports Tide nor
calls an indirect runtime callback. Its installed probe uses the existing
executable directory. The unnecessary temporary directory was also removed.

Formatting moved an existing narrow Semgrep annotation off its urllib call.
Restoring that annotation to the call fixed Semgrep without broad suppression.
The first Codex review found one actionable digest regression: the legacy digest
consumer treated the new report schema as old data, producing false zero totals.
It now rejects versioned reports before rendering or posting. Dry-run and post
regressions pass. Digest migration is deliberately deferred; the error directs
users to the canonical report command.

A duplicate inherited/worktree push URL caused a real preflight rejection. Only
the worktree-specific push URL was corrected; the shared remote was preserved.
A development check initially selected the isolated install interpreter without
Ruff; selecting the host interpreter restored the exact passing check.

## Review and retained scope

Post-PR Codex review 1 on 23e41ed found the digest issue above; it was not clean.
Review 2 used `codex exec review --base origin/main` on correction commit
047831cdbd926898ec69e8ba18dc3c4ddd0fcd8c and exited zero at
2026-09-15T07:57:03Z: "No actionable regressions were found." The reviewer
confirmed the 792-test result and report/lint/format/type/doc/invariant checks.
The desktop-bundled CLI was used because the older global executable cannot run
the configured Astra model. Optional Linear MCP startup emitted an unrelated
authorization warning; the code review completed. Independent Codex-20 review
also found no additional high-confidence defect in its bounded final scope.

## Installation checkpoint

CI on correction commit 047831c: Semgrep, boundary, doc-sync validation and
Workers Builds succeeded; invalidate-stale-tide was skipped. Trusted ledger and
Tide replay checks failed. The precise remaining trusted guard rejection is
`existing writer boundary source changed: src/wea_cli/cli.py`.

This is an unresolved protected installation gate, not an all-green PR.
`oled/changes/wea-vnext-tide/design.md` and its `verification.md` require code
review followed by a one-time operator exception for the exact PR/head and
current main. Funding authorization does not supply that exception. Agent0 must
present the final evidence commit and current main at that checkpoint. No guard,
allowlist, workflow or BDD change bypasses it.

Lean cut: reuse existing canonical adapter and runtime guidance, native Git and
the standard library; remove the redundant standalone report module. No BDD,
ledger, executor, identity, workflow or settlement changes. Historical private
API-push helper functions remain undispatched; their removal is not required.

Local full test/install/report/remote logs are under `.wea_runs/980/`, including
`broad-first.log`, `broad-final.log`, `broad-reviewed-head.log`,
`focused-data-boundary.log`, `codex-review-1.log`, `codex-review-2.log`, `push-proof.json`,
`demo.py`, `report-final.json`, `report-human.txt` and freshness readbacks.
Only redacted summaries are tracked; diagnostic logs remain local.
Visible agent/tool transcripts remain in the local Codex session records.
