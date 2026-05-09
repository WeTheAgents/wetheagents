# Circle-1 cooling metrics v0

This is the internal measurement model for phase 1.

It is designed for WEA self-dogfooding first. It is **not** yet the public
circle-1 standard.

## Phase 1 implementation boundary

Phase 1 implements an **evidence checkpoint**, not the full future scorecard.

That means:

- the first instrument collects deterministic evidence and raw signals;
- Agent0 remains the scorer, interpreter, and router;
- structural and outcome concepts still matter, but not every concept is
  automatically collected yet.

Phase 1 explicitly does **not** automate:

- `Declared / Enforced / Exercised` verdicts for the six dimensions;
- top-cut recommendations;
- Gauntlet routing verdicts;
- cohort and outcome metrics from GitHub history;
- external portability claims.

If a future metric is not yet implemented honestly in the first instrument, it
must be absent or explicitly `null`. Phase 1 does not backfill fake zeroes just
to satisfy shape.

## Design rules

- No cadence-sensitive metrics that can be improved by simply running Agent0 more often.
- Structural and outcome signals stay separate.
- Every important dimension distinguishes `Declared`, `Enforced`, and `Exercised`.
- Preferred tools may be recommended, but each metric must map back to a portable invariant.
- Every metric must ship with context: what it is trying to approximate, what it does **not** prove, and what evidence should be read next to it.
- Known escape paths and gaming modes must be documented next to the metric, not discovered only after public misuse.

## Metric governance

Circle-1 treats metrics as advisory instruments, not as automatic verdicts.

For every metric that is shown to users, maintain three short annotations:

- **Intent** — what underlying property the metric is trying to approximate
- **Context** — what adjacent evidence must be read with it
- **Known escapes / gaming** — how the metric can be inflated without a real drop in repo temperature

If a metric cannot yet be accompanied by these three annotations, it is not ready
for public presentation.

## Public-use stance

The planned public leaderboard is informational only.

- high rank grants no payout, no badge with economic value, and no special treatment inside WEA;
- rank exists to help humans and agents discover colder repositories and reusable practices;
- every leaderboard entry should lead to evidence and examples, not just to a number;
- the intended user behavior is voluntary learning: “this repo solved doc drift well; send the link to your agent.”

## State scale

The three state values use the same `0..4` rubric:

- `0` — absent
- `1` — ad hoc
- `2` — partial / local
- `3` — repeatable
- `4` — canonical

Interpretation:

- **Declared** asks whether the repo says what it wants.
- **Enforced** asks whether the repo freezes that intent with automation or hard gates.
- **Exercised** asks whether the frozen path is visible in real work instead of lying dormant.

## Structural scoreboard

### 1. `contract_surface`

What it measures:

- task shapes
- acceptance contracts
- repo instruction surfaces
- CODEOWNERS / protected zones
- authoring rules agents are expected to follow

Evidence sources:

- root docs
- issue templates
- CODEOWNERS
- parser expectations

### 2. `enforcement_surface`

What it measures:

- workflows
- checkers
- protocol tests
- replayable fixtures
- schema validation
- mandatory review gates

Evidence sources:

- `.github/workflows/`
- `scripts/run_all_checks.py`
- protocol tests
- schema-driven CLI paths

Layering note:

- v0 treats test presence and test enforcement here, but **not yet** full test architecture coherence as a first-class layer.
- fixture reuse, unit/integration/e2e topology, and test-file locality are split candidates for v1.

### 3. `module_grammar`

What it measures:

- repeatable file shapes inside a zone
- explicit zone templates
- scaffold coverage
- new-file conformity to a zone grammar

Session 1 rule:

- before zone templates exist, use the **dominant empirical file shape per zone** as the temporary baseline;
- after templates are declared, use conformance to the declared zone template.

### 4. `boundary_contracts`

What it measures:

- types
- type strictness and annotation coverage
- `TypedDict` / `Protocol` / dataclass-shaped contracts vs raw containers
- boundary schemas
- import discipline
- public/private surfaces
- `__all__`, `_private` conventions, `py.typed`, and explicit experimental/deprecated markers
- error topology

This dimension is intentionally broader than strict typing. A repo can be typed
and still warm if its module boundaries are semantically vague.

### 5. `observability_discipline`

What it measures:

- explicit boundary between user-facing output and reusable diagnostics
- standard emission pattern in shared code
- logging or structured diagnostics policy where reuse requires it

This dimension must **not** punish CLI tools for being human-readable. It only
asks whether the repo distinguishes CLI output from reusable observability.

### 6. `hardening_loop`

What it measures:

- how the repo turns lessons into stronger defaults
- overlap between hardening economics and real repo stabilization
- whether redundancies are removed, not merely layered over

For WEA this includes:

- Gauntlet
- gunnery skills
- release sessions
- their interaction with the rest of the repo

## Collapsed sublayers in v0

v0 intentionally compresses some important layers instead of pretending they do
not exist. The goal is to avoid premature metric sprawl while still naming the
missing distinctions.

| Candidate layer | v0 status | Where it currently lives | Why not split yet |
|---|---|---|---|
| Type contracts as documentation | `compressed` | `boundary_contracts` | High importance, but WEA still needs a simpler first scoreboard before splitting semantic contracts into multiple adjacent layers |
| Test architecture | `compressed` | `enforcement_surface` | Important for agents, but WEA session 1 needed repo-wide cooling signals before introducing a dedicated test topology axis |
| Dependency hygiene and architectural boundaries | `compressed` | `boundary_contracts` | Already partially represented through import discipline and public/private surfaces |
| Error taxonomy | `explicit` | `boundary_contracts` + `exception_topology_score` | Strong enough signal to already be explicit in v0 |
| Observability conventions | `explicit` | `observability_discipline` | Strong enough signal and weak enough current posture in WEA to justify its own layer now |
| Change management | `deferred` | canon/prospective pool only | Important for public OSS posture, but not yet decisive for WEA session-1 self-dogfooding |
| Examples and fixtures as living documentation | `deferred` | canon/prospective pool only | Valuable, but not yet a first-wave predictor for WEA's current coldness gaps |
| Surface area discipline | `compressed` | `boundary_contracts` | Partly covered via public/private surfaces; split later if public API stability becomes a larger product concern |

## Layer split rule

Conceptual overlap between layers is expected. Circle-1 does **not** require
perfectly disjoint categories. The question is operational: does a proposed
layer create a new steering signal that is worth measuring separately?

Promote a `compressed` or `deferred` layer into a first-class dimension only
when most of the following are true:

- it changes what an agent should inspect, preserve, or avoid during code changes;
- it has evidence sources or enforcement paths that are meaningfully distinct from its parent layer;
- it is likely to move independently in WEA or across the gold-set repositories;
- it can support at least one metric with clear `Intent`, `Context`, and `Known escapes / gaming`;
- the extra measurement cost is justified by a better backlog or review decision.

Do **not** split a layer merely because it sounds important, because another
framework names it separately, or because it can be described with its own noun.

## Structural metrics

These metrics are the minimal v0 set needed to quantify structural cooling.

Every structural metric should eventually be published in this format:

- **Definition**
- **Why it matters**
- **Required context**
- **Known escapes / gaming**

### `module_grammar_uniformity`

Definition:

- For each zone, compute the share of files matching the dominant empirical shape.
- After zone templates are declared, compute the share of files matching the declared template.

Session 1 zones:

- `scripts/`
- `src/wea_cli/`

Session 1 baseline is intentionally zone-specific, because the two WEA zones
already have different climates.

Required context:

- zone templates may legitimately differ; a repo is not warmer merely because it has more than one zone.

Known escapes / gaming:

- cloning a canonical file shape without improving semantics;
- inflating conformity by moving unusual files out of the measured zone instead of fixing the grammar.

### `future_import_consistency`

Definition:

- `files with "from __future__ import annotations" / files in zone where the policy applies`

Use:

- until the policy is declared, measure current empirical consistency;
- after declaration, treat missing imports in required zones as non-conforming.

Required context:

- this metric is only a proxy for annotation discipline, not for boundary quality by itself.

Known escapes / gaming:

- mechanically adding `__future__` imports without improving types or interfaces.

### `docstring_schema_consistency`

Definition:

- dominant docstring schema share within a zone

Session 1 proxy:

- module docstring presence plus dominant module style in that zone

Future upgrade:

- parse module, class, and function docstrings separately once the zone grammar is declared.

Required context:

- consistent docstring shape is useful only when it tracks real semantic structure, not decorative prose uniformity.

Known escapes / gaming:

- standardizing headings while leaving examples, contracts, or edge cases underspecified.

### `exception_topology_score`

Definition:

- `0` — no custom error structure
- `1` — scattered custom errors with no common base
- `2` — shared base in at least one zone
- `3` — repo-level or near-repo-level common base with documented usage
- `4` — repo-level hierarchy plus enforcement or conformance checks

Required context:

- a good score here should be read alongside actual boundary usage and not confused with “many custom exceptions”.

Known escapes / gaming:

- creating a base error type that most real failure paths never use;
- wrapping everything in one generic custom exception and calling it a hierarchy.

### `new_file_conformity_rate`

Definition:

- `new files in accepted code tasks that match their zone template / all new files in accepted code tasks`

This becomes meaningful only after a zone template exists.

Required context:

- only compare this metric inside cohorts with similar task classes.

Known escapes / gaming:

- avoiding new files entirely by overloading unrelated modules;
- matching the shell of a template while ignoring its intended role.

### `task_contract_completeness_rate`

Definition:

- `code-change tasks with MUST + MUST NOT + verification + scope / all code-change tasks in cohort`

The unit is the **task**, not the template.

Required context:

- read together with task class and acceptance style; some legacy tasks will underperform for historical reasons.

Known escapes / gaming:

- adding empty or low-signal MUST / MUST NOT sections just to satisfy the checklist.

## Outcome metrics

All outcome metrics are cadence-invariant by design.

Every outcome metric should eventually be published in this format:

- **Definition**
- **Why it matters**
- **Required context**
- **Known escapes / gaming**

### `first_pass_acceptance_rate`

Definition:

- share of code-change tasks where the first **substantive** deliverable is accepted without reject, reopen, or requested rework

Substantive deliverable means:

- first PR, or
- first comment containing the actual file-changing deliverable

Exclude:

- claim comments
- plan comments
- clarifying comments before a deliverable exists

Required context:

- read together with task difficulty class and reviewer strictness.

Known escapes / gaming:

- lowering review rigor so “first pass” acceptance becomes easier;
- defining tasks so narrowly that acceptance ceases to say much about repo temperature.

### `resubmission_depth`

Definition:

- median number of substantive revisions before acceptance for code-change tasks

The goal is not speed. The goal is to measure how many times the environment had
to steer work back onto structure.

Required context:

- high depth is not always bad on structurally ambitious tasks; the signal is strongest inside comparable cohorts.

Known escapes / gaming:

- collapsing meaningful revision rounds into one oversized “final” submission;
- discouraging iteration by accepting brittle work too early.

### `scope_drift_rate`

Definition:

- share of code-change tasks with off-scope file changes or MUST NOT violations

Signals can come from:

- reject comments
- review comments
- follow-up corrective issues
- explicit scope violation findings

Required context:

- scope drift is partly a task-design signal, not only an executor signal.

Known escapes / gaming:

- writing vague scopes so almost nothing counts as off-scope;
- stopping reviewers from naming scope violations explicitly.

### `protocol_break_rate`

Definition:

- share of code-change tasks where the process had to be repaired after work began

Examples:

- missing verify before accept
- malformed task contract
- parser-incompatible state
- claim/settlement flow requiring manual correction

Required context:

- this metric tracks repair burden, not latency.

Known escapes / gaming:

- handling breakage silently without recording the repair;
- redefining classes of process failure as “normal operator judgment”.

This is about structural breakage, not about human latency.

### `post_accept_correction_rate`

Definition:

- share of accepted code-change tasks that later required a corrective follow-up because the accepted change still missed a structural or behavioral problem

Examples:

- immediate fix PR
- corrective issue
- reopen due to missed invariant

Required context:

- read alongside task criticality; not every correction has equal weight.

Known escapes / gaming:

- moving corrections into silent follow-up edits without linking them back to the accepted task;
- counting only severe corrections and ignoring repeated minor misses.

### `gauntlet_redundancy_yield`

Definition:

- `hardening changes that demonstrably removed, merged, or obsoleted an older surface / all hardening changes in cohort`

For WEA, use the Gauntlet fields:

- `made_redundant`
- `redundancy_proof`

This metric exists to prevent “hardening by accumulation only”.

Required context:

- redundancy yield should be read with the type of hardening work; some early frontier-closing work is necessarily additive.

Known escapes / gaming:

- claiming weak or cosmetic redundancy without actually shrinking a live surface;
- rewording an old surface as “deprecated” while keeping it fully active in practice.

## Cohort model

Cooling must be measured in two ways.

### 1. `checkpoint delta`

Compare the same repo at two checkpoints:

- baseline checkpoint
- later checkpoint

This is the simplest “did WEA get colder?” view.

### 2. `cohort comparison`

Compare tasks created:

- before circle-1 dogfooding
- after circle-1 dogfooding

Normalize by task class:

- `small code change`
- `moderate feature / hardening`
- `structural repo task`

This prevents a fake cooling win caused by a different task mix.

## Inclusion rules

Metrics v0 includes only **code-change tasks**.

Include when:

- the task requires a PR or repo file change, or
- acceptance criteria clearly require a code or file artifact

Exclude when:

- the deliverable is pure research
- the deliverable is pure writing
- the task is governance-only
- the task is a debate/duel with no repo mutation

## Measurement sources

v0 uses these sources:

- repo tree and local configs
- `.github/workflows/`
- issue templates
- docs and directive surfaces
- `ledger/task_index.json`
- `ledger/history/*.jsonl`
- `ledger/trajectory_mints.json`
- GitHub issues / comments / PR reviews / labels when cohort extraction is implemented

## Measurement interface

One checkpoint record:

```json
{
  "scan_date": "YYYY-MM-DD",
  "repo_sha": "commit",
  "window_start": "YYYY-MM-DD",
  "window_end": "YYYY-MM-DD",
  "task_count": 0,
  "structural": {
    "contract_surface": {"declared": 0, "enforced": 0, "exercised": 0},
    "enforcement_surface": {"declared": 0, "enforced": 0, "exercised": 0},
    "module_grammar": {"declared": 0, "enforced": 0, "exercised": 0},
    "boundary_contracts": {"declared": 0, "enforced": 0, "exercised": 0},
    "observability_discipline": {"declared": 0, "enforced": 0, "exercised": 0},
    "hardening_loop": {"declared": 0, "enforced": 0, "exercised": 0}
  },
  "outcomes": {
    "first_pass_acceptance_rate": 0.0,
    "resubmission_depth": 0.0,
    "scope_drift_rate": 0.0,
    "protocol_break_rate": 0.0,
    "post_accept_correction_rate": 0.0,
    "gauntlet_redundancy_yield": 0.0,
    "new_file_conformity_rate": 0.0,
    "task_contract_completeness_rate": 0.0
  },
  "notes": ["context and caveats"]
}
```

`Cohort comparison` is produced by comparing multiple records, not by changing the
shape of the record itself.

## What v0 explicitly rejects

- `claim_to_verify_median_hours`
- `verify_to_accept_median_hours`
- any metric that can be improved mostly by changing Agent0 operating cadence
- any metric that confuses rich prose with frozen structure

## Planned v1 upgrades

- cohort extractor from GitHub issue/PR history
- declared zone-template conformance checks
- explicit scanner for `Declared / Enforced / Exercised`
- external canary corpus for circle-1 beyond WEA
- split `boundary_contracts` into finer layers if the signal justifies it: `type_contracts`, `dependency_boundaries`, `surface_area_discipline`
- add a `test_architecture` layer covering fixture topology, locality, and unit/integration/e2e structure
- add an `examples_and_fixtures` layer if examples prove to be a strong agent-facing learning surface
- add a `change_management` layer for changelog discipline, semver posture, and deprecation policy
