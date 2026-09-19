# Circle-1 orientation experiment, 2026-09-19

## Steward assessment and correction

The operator asked Agent0 to assess whether Circle-1 explains its purpose and
direction, improve unclear documentation, then let Codex-2 and Codex-19 choose
their own useful next step. This is editorial guidance and an unpaid exploration,
not a new BDD contract, funded Plan, or competition.

The initial external main was `36a71440840351aa462e61a8ad5955881f55ecb0`.
Its README explained package installation, scanning and ownership boundaries.
It did not give newcomers a clear project direction or way to choose useful work.
The older Gauntlet document also lacked a historical-context notice. Purpose and
research caveats existed, but readers had to assemble them from several documents.

[Circle-1 PR #1](https://github.com/WeTheAgents/circle-1/pull/1) adds the motto
"Make the next correct change easier to predict", a newcomer guide, entry links,
and a historical notice on the Gauntlet document. The guide separates current
scanner behavior, research proposals, and old WEA baselines. It permits an agent
to conclude that no change is useful and invites evidence-backed retirement
proposals. It does not alter scanner code, metrics, contracts, or workflow behavior.

The four-file documentation change passed the required checks:
`python -m pytest -q` (209 passed, 15 skipped), `ruff check src tests` (clean),
and `pyright src` (zero errors). All 17 local documentation links resolve.
Native Codex review found the docs consistent with current scanner behavior.
PR CI passed. Manual merge: `73fc1c351a754d70819e95ade8a806830922cd18`,
actual GitHub time `2026-09-19T03:28:51Z`.

## Launch and interpretation boundaries

Both agents received the same open invitation: read the repository, decide what
is useful, and take one bounded step. No defect, required issue, score improvement,
or preferred conclusion was assigned. Each must retain its own initial reading
before seeing the other's findings. Discussion and public issues about public
Circle-1 evidence are authorized. A behavioral implementation requires an agreed
scope. There is no new payment promise, funded Work, Release session, or automation.

Both worktrees start at the exact merged documentation revision above:

| Identity | Circle-1 worktree | Branch | Session context |
| --- | --- | --- | --- |
| Codex-2@codex | `D:/GitHub/circle-1-agent-codex2-20260919` | `codex/circle1-arrival-codex2-20260919` | New subagent with no inherited conversation |
| Codex-19@codex | `D:/GitHub/circle-1-agent-codex19-20260919` | `codex/circle1-arrival-codex19-20260919` | Existing identity's prior session resumed for this new assignment |

The tool refused a second fresh subagent with `agent thread limit reached`.
Agent0 reused the existing Codex-19 session instead of claiming two fresh sessions.
The experiment therefore observes fresh and returning orientation; it is not a
controlled comparison between two cold starts. Codex-19 also disclosed that an
unsolicited colleague message about coverage arrived before its own initial note.
Its note is retained, but cannot establish blindness to the colleague's finding.
Both identities share the same operator/account, so separate findings do not
establish independent control.

Fresh Agent0 source CLI reads at `2026-09-19T03:24:08.746935Z` (Codex-2) and
`2026-09-19T03:24:17.216679Z` (Codex-19) observed the existing grants as active.
The agents must independently read their own grants before domain activity.
No Access was reissued. The immutable Domain registry pin remains
`36a71440840351aa462e61a8ad5955881f55ecb0`; the worktree revision is a later
documentation change in that same external repository, not a registry update.

Circle-1 remains public and WEA remains private. Public contributions must not
include private genomes, Access receipts, balances, task histories, or internal
logs. The main WEA checkout and its saved local changes remain untouched.

## Actual observations

### Codex-2: what did the scan cover?

The fresh session inferred that Circle-1 supplies evidence for predictable
changes, rather than universal scores or WEA task generation. It chose to test
whether a newcomer could scan a public target and interpret coverage.

Its small experiment supplied a profile whose path named `src/circle1/`.
The scanner completed with both zones at `total=0`, `conforming=0`, `rate=1.0`,
and aggregate `declared=3`, `enforced=0`, `exercised=1`. Eight non-init Python
modules actually exist in that directory. Agent0 checked the retained output and
the public source: `SESSION_1_ZONES` and `_ZONE_PATHS` still select `scripts/`
and `src/wea_cli/`; the template's path does not choose the target directory.

Codex-2 published [Circle-1 Issue #2](https://github.com/WeTheAgents/circle-1/issues/2),
"Clarify fixed zone coverage before non-WEA use of circle1-score", at
`2026-09-19T03:32:38Z`. Its exact public body was verified; SHA-256
`47ebdd3ccf80f85706c4ffb362c2e26eb3a2df29eb2a31ac0ea357d9c7cca9e9`.
Relevant existing tests passed: 17 passed, 5 optional private-target cases skipped.
The issue correctly distinguishes an old supported-layout limitation from a
proven regression. It asks whether to clarify coverage or separately agree
profile-driven zones. No implementation was assumed or performed.

### Codex-19: which source state did the scan measure?

The returning session inferred that useful evidence reduces uncertainty in real
changes and that scanner scores alone do not establish success. It independently
read its identity/Access sources and chose to examine checkpoint provenance,
especially dirty target checkouts, from the README and migration contract.
Its experiment used a synthetic directory without Git metadata and a one-rule
docstring profile. With `--repo-sha` omitted, the output label was empty.
With `--repo-sha caller-label-not-verified`, the label was copied unchanged.
Removing the source docstring changed conformance from 1/1 to 0/1 under that same
label. All three commands exited zero. This demonstrates caller-supplied metadata;
it does not claim to exercise a real dirty Git checkout or verify a real commit.

Agent0 checked the retained JSON and the source that copies the supplied label.
Codex-19 found no regression against that interface and published no Issue,
comment or PR. Its existing score tests passed: 17 passed, 5 optional live-target
cases skipped. It suggested an optional README sentence explaining that the tool
reads current files while the caller preserves source state and profile evidence.
Automatic Git discovery or validation was not proposed as an already accepted rule.

After its note, Codex-19 read public Issue #2 and found no disagreement with that
separate coverage question. The agents exchanged coordination messages; this run
did not produce a joint public discussion or a new implementation.

Both agents' own initial notes, source readbacks, experiments and final responses
are retained under `.wea_runs/orientation/codex2/` and
`.wea_runs/orientation/codex19/` in the separate WEA orientation worktree.

## Steward conclusion and next decision

Both sessions could explain the project purpose and choose a concrete inquiry.
Codex-2 created one reproducible public proposal. Codex-19 exercised judgment by
retaining a valid observation without inventing a defect or additional ticket.
These observations support the usefulness of the entry documents for these two
sessions. They do not establish a general onboarding success rate or isolate the
documentation as the sole cause.

The evidence does not show that the project's purpose is obsolete. It does show
that some operating assumptions still come from the original WEA layout and
from callers that already know how to preserve measurement context. Target paths
and input provenance deserve explicit treatment before broader portability claims.

The next useful decision is the scope of Issue #2: clarify supported layouts and
zero-coverage interpretation, or separately agree profile-driven zone selection.
The provenance clarification can remain a small editorial follow-up. Do not turn
these observations into a new scoring rule or funded Work without its own scope
and authority. Both agent worktrees are unchanged; no worker implementation,
funding, new grant, registry revision, or background loop was created.

## Remaining observation

The original Access endpoints are unchanged: Codex-2 ends at
`2026-09-25T19:05:41.605830Z`; Codex-19 at `2026-09-25T19:06:43.406992Z`.
Real post-endpoint observation remains pending. This experiment does not replace it.

BDD alignment: 100% within this scope; no protocol or scanner behavior changed.
