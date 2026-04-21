# Circle-1 cooling metrics v0

This is the internal measurement model for phase 1.

It is designed for WEA self-dogfooding first. It is **not** yet the public
circle-1 standard.

## Design rules

- No cadence-sensitive metrics that can be improved by simply running Agent0 more often.
- Structural and outcome signals stay separate.
- Every important dimension distinguishes `Declared`, `Enforced`, and `Exercised`.
- Preferred tools may be recommended, but each metric must map back to a portable invariant.

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
- boundary schemas
- import discipline
- public/private surfaces
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

## Structural metrics

These metrics are the minimal v0 set needed to quantify structural cooling.

### `module_grammar_uniformity`

Definition:

- For each zone, compute the share of files matching the dominant empirical shape.
- After zone templates are declared, compute the share of files matching the declared template.

Session 1 zones:

- `scripts/`
- `src/wea_cli/`

Session 1 baseline is intentionally zone-specific, because the two WEA zones
already have different climates.

### `future_import_consistency`

Definition:

- `files with "from __future__ import annotations" / files in zone where the policy applies`

Use:

- until the policy is declared, measure current empirical consistency;
- after declaration, treat missing imports in required zones as non-conforming.

### `docstring_schema_consistency`

Definition:

- dominant docstring schema share within a zone

Session 1 proxy:

- module docstring presence plus dominant module style in that zone

Future upgrade:

- parse module, class, and function docstrings separately once the zone grammar is declared.

### `exception_topology_score`

Definition:

- `0` — no custom error structure
- `1` — scattered custom errors with no common base
- `2` — shared base in at least one zone
- `3` — repo-level or near-repo-level common base with documented usage
- `4` — repo-level hierarchy plus enforcement or conformance checks

### `new_file_conformity_rate`

Definition:

- `new files in accepted code tasks that match their zone template / all new files in accepted code tasks`

This becomes meaningful only after a zone template exists.

### `task_contract_completeness_rate`

Definition:

- `code-change tasks with MUST + MUST NOT + verification + scope / all code-change tasks in cohort`

The unit is the **task**, not the template.

## Outcome metrics

All outcome metrics are cadence-invariant by design.

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

### `resubmission_depth`

Definition:

- median number of substantive revisions before acceptance for code-change tasks

The goal is not speed. The goal is to measure how many times the environment had
to steer work back onto structure.

### `scope_drift_rate`

Definition:

- share of code-change tasks with off-scope file changes or MUST NOT violations

Signals can come from:

- reject comments
- review comments
- follow-up corrective issues
- explicit scope violation findings

### `protocol_break_rate`

Definition:

- share of code-change tasks where the process had to be repaired after work began

Examples:

- missing verify before accept
- malformed task contract
- parser-incompatible state
- claim/settlement flow requiring manual correction

This is about structural breakage, not about human latency.

### `post_accept_correction_rate`

Definition:

- share of accepted code-change tasks that later required a corrective follow-up because the accepted change still missed a structural or behavioral problem

Examples:

- immediate fix PR
- corrective issue
- reopen due to missed invariant

### `gauntlet_redundancy_yield`

Definition:

- `hardening changes that demonstrably removed, merged, or obsoleted an older surface / all hardening changes in cohort`

For WEA, use the Gauntlet fields:

- `made_redundant`
- `redundancy_proof`

This metric exists to prevent “hardening by accumulation only”.

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
