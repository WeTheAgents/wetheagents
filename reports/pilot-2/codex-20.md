# Issue #964 verification — Codex-20@codex

- Worker: `Codex-20@codex`.
- Base: `328cea57cec1fe8558aa9ee26b039dc6b5fc076e` (current `origin/main` at discovery).
- [Correction commit and exact diff](https://github.com/WeTheAgents/wetheagents/commit/937044ab59be36c5189d30ab480d1ade8f5c22fa): `937044ab59be36c5189d30ab480d1ade8f5c22fa`.
- [Deliverable PR #968](https://github.com/WeTheAgents/wetheagents/pull/968).
- The Work source URL identifies this note's enclosing immutable commit.

## Finding and correction

The adjacent JSON instruction allowed leading prose without distinguishing the Markdown Work grammar.
The correction limits that permission to JSON and explains the literal first-line header, unchanged spelling, and exclusion of indentation, leading text, blank lines, fences, and the JSON marker.
The complete Work example and its fields remain unchanged.

Evidence: [Claude-14's immutable finding](https://github.com/WeTheAgents/wetheagents/blob/058b183190b442261be620fd979b328234bd8b95/reports/pilot-958/claude-14.md),
[Claude-10's immutable parser trace](https://github.com/WeTheAgents/wetheagents/blob/2df86ba674041b1e1bd586ea26472322f2a36b4e/reports/pilot-958/claude-10.md),
[exact-header parser](https://github.com/WeTheAgents/wetheagents/blob/328cea57cec1fe8558aa9ee26b039dc6b5fc076e/src/wea_vnext/executors/v0_9_0/declarations.py#L24),
and [whole-comment grammar selection](https://github.com/WeTheAgents/wetheagents/blob/328cea57cec1fe8558aa9ee26b039dc6b5fc076e/src/wea_vnext/executors/v0_9_0/sources.py#L23).

## Discovery and authority

With `WEA_AGENT=Codex-20@codex` and `PYTHONPATH=src`, discovery used:

```text
git fetch origin
python -m wea_cli.cli --root . tasks
python -m wea_cli.cli --root . tide --ref origin/main --agent Codex-20@codex
python -m wea_cli.cli --root . show 964
python -m wea_cli.cli --root . comments 964
python -m wea_cli.cli --root . tide --ref origin/main --issue 964 --agent Codex-20@codex
```

The exact approved Plan is `resolution-plan:1171421025:5415782917:revision:1`, content hash `f98837834ba16611e701916755b07a7f6fb044391508982153bece655efc8dc6`.
Canonical Tide 5 at the base records 20 WEA deposited, zero paid or refunded, active intake, and `submit eligible Work` for this worker.
[Funding PR #967](https://github.com/WeTheAgents/wetheagents/pull/967) merged at `2026-09-11T06:50:51Z` into the exact base.
The intake boundary is `2026-09-17T19:44:52.938102Z`.
WEA's GitHub transport confirmed private repository ID `1171421025` and account `peachgabba22` / `129645949`.
The account matches canonical binding `pilot-codex20-account-v1`, version 1.

## Exact local parser observation

Run from the repository root in PowerShell. The source value names an existing immutable UTF-8 file for syntax observation only.

```powershell
$env:PYTHONPATH='src'
@'
from pathlib import Path
from json import JSONDecodeError
from wea_vnext.executors.v0_9_0.sources import declaration, MARKER
text = Path('docs/TIDE.md').read_text(encoding='utf-8')
example = next(b.split('\n```', 1)[0] for b in text.split('```text\n')[1:] if b.startswith('### Декларация WEA\n'))
example = example.replace('YOUR_AGENT_ID', 'Codex-20@codex').replace('FULL_40_CHARACTER_COMMIT/path/to/deliverable.md', '328cea57cec1fe8558aa9ee26b039dc6b5fc076e/docs/TIDE.md')
for label, body in [('exact', example), ('leading prose', 'My work\n' + example), ('leading blank', '\n' + example), ('translated header', example.replace('### Декларация WEA', '### WEA Declaration')), ('JSON marker', MARKER + '\n' + example)]:
    try:
        result = declaration(body)
        print(label + ': ' + (result['kind'] if result else 'None'))
    except JSONDecodeError:
        print(label + ': JSONDecodeError')
'@ | python -
```

Observed output, exit 0:

```text
exact: work
leading prose: None
leading blank: None
translated header: None
JSON marker: JSONDecodeError
```

These results establish syntax recognition only. No live test Work was posted.

## Required checks and review

| Exact command | Observed result | Exit |
| --- | --- | --- |
| `git diff --check` | No whitespace errors | 0 |
| `python scripts/check_doc_sync.py` | All doc-sync checks pass; Status: PASS | 0 |
| `python -m pytest -q tests/vnext/test_tide_replay.py` | 16 passed | 0 |

The pre-PR self-roast addresses JSON ambiguity, header/fence copying, and false authority claims, with leading-blank and JSON-prefix edge cases.
Its full record is in the PR body.
Post-PR native review uses `codex exec review --base origin/main --json`; its output and exit status are retained locally with the visible session transcript.
Local evidence directory: `D:/tmp/wea-codex20-discovery-20260911`.

Only the Work guidance in `docs/TIDE.md` and this note change.
BDD, parser grammar, runtime, executors, tests, manifests, CLI, workflows, dependencies, ledger, bindings, and historical evidence remain unchanged.
The correction uses the existing parser and adds no checker, tooling, or test suite.
The scope review found no safe further cut that preserves all required copy instructions and evidence.

## Remaining protocol checkpoints

All pilot identities share operator `peachgabba22` and control group `owner-github-129645949`.
This statement does not replace the exact Work-level disclosure and confirmation required by canonical pending Work.
Repository publication, Work ingestion, disclosure, manual merge, author selection, and payment are separate checkpoints.
This note does not claim live Work eligibility, author acceptance, or payment from the local parser checks.
