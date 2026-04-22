# Circle-1 <-> Gauntlet coordination

This document explains how `circle-1` and `Gauntlet` work together inside WEA.

The goal is not to merge them into one mechanism. The goal is to create a
closed loop:

`observe -> propose -> harden -> monitor -> recalibrate`

`circle-1` gives WEA a language for repo temperature and agent predictability.
`Gauntlet` gives WEA a familiar hardening machine for turning known weaknesses
into concrete protective artifacts. After those artifacts land, `circle-1`
monitors whether the environment actually became colder.

## Short version

- `circle-1` asks: what should be cooled, how do we describe it, and how will we measure it?
- `Gauntlet` asks: what weakness in the harness should we close right now, and what protection or simplification proves that closure?
- A Gauntlet mint is **not** a temperature verdict.
- A circle-1 score is **not** a hardening artifact.
- Together they form a feedback loop.

## Different jobs

### Circle-1

Primary role:

- identify temperature gaps in WEA;
- define portable invariants and preferred tools;
- build baselines, scans, and scorecards;
- decide what evidence should be monitored after changes land.

Typical artifacts:

- baseline memos;
- canon updates;
- cooling metrics;
- module census;
- issue triage and expected metric-shift notes.

Circle-1 is strongest when the question is:

- "What are we trying to stabilize?"
- "Which layer is warm?"
- "How will we know whether the repo got colder?"

### Gauntlet

Primary role:

- let agents harden the WEA harness through familiar trajectories `T1..T6`;
- reward concrete closures of weaknesses;
- require evidence, explicit frontier naming, and redundancy pressure.

Typical artifacts:

- checker;
- test or replayable fixture;
- fail-safe or recovery path;
- tighter contract or parser-friendly rule;
- deprecation, merge, or removal of redundant surfaces.

Gauntlet is strongest when the question is:

- "What concrete weakness can we close?"
- "What artifact proves the closure?"
- "What older path became redundant?"

## What each side does not do

Circle-1 does not:

- mint rewards;
- certify that a frontier is closed by itself;
- replace Gauntlet trajectory logic with a temperature score.

Gauntlet does not:

- decide repo temperature;
- track whether pipeline linearity improved;
- treat a successful hardening slot as automatic proof that WEA is colder.

That last point matters. A strong hardening change can still be:

- too local to move a repo-level metric;
- partially adopted;
- offset by fresh entropy elsewhere;
- helpful for safety but neutral for agent predictability.

## Coordination model

### 1. Observe

A signal appears from one of two places:

- `circle-1` baseline, scan, or cohort comparison identifies a warm layer;
- agents already see a harness weakness and frame it directly as a Gauntlet problem.

### 2. Classify

Before opening work, answer five questions:

1. Which `circle-1` dimension does this touch?
2. Is the weakness already concrete enough for a Gauntlet trajectory?
3. Is the expected value mostly understanding, hardening, or both?
4. What metric or checkpoint should move if the change works?
5. What older ambiguity, path, or artifact should become redundant?

### 3. Deliver

Choose one of three lanes:

#### Lane A: `circle-only`

Use when the deliverable is mainly diagnostic or framing.

Examples:

- baseline memo;
- module grammar census;
- canon update;
- measurement extractor;
- backlog triage.

#### Lane B: `gauntlet-only`

Use when agents already understand the weakness in harness terms and can close
it directly through `T1..T6`.

Examples:

- new invariant checker;
- missing replayable test;
- circuit breaker;
- deprecation of a redundant routine.

#### Lane C: `circle -> gauntlet -> circle`

Use when the weakness is visible as a temperature problem, but the closure still
needs a hardening artifact and later monitoring.

This is the default bridge lane for overlap work.

### 4. Monitor

After a Gauntlet-backed change lands, `circle-1` records what happened.

It should ask:

- did the intended metric move?
- did a different adjacent metric get worse?
- did the improvement stay local, or did it change repo behavior more broadly?
- did the "made redundant" claim hold in practice?

This is where `circle-1` closes the feedback loop. Gauntlet implements. Circle-1
observes the system after implementation.

### 5. Recalibrate

Possible outcomes:

- the change cooled the intended layer;
- the change hardened something useful but did not move temperature much;
- the change was too additive and needs a follow-up T5-style collapse;
- the original temperature model was wrong and should be updated.

## Routing rules

### Rule 1. No double counting

One deliverable should not be rewarded both as:

- `circle-1` research/discovery, and
- the exact same Gauntlet closure.

The phases may be linked, but they are not the same unit of work.

### Rule 2. Gauntlet mint does not equal cooling proof

A minted slot proves a hardening event happened under Gauntlet rules. It does
not, by itself, prove a repo-level temperature improvement.

### Rule 3. Circle-1 may nominate, not override

`circle-1` may say:

- this gap looks like `T4`;
- this change should probably prove redundancy;
- these metrics should be watched afterwards.

But Gauntlet acceptance still depends on normal trajectory criteria and the
Gauntlet evaluator.

### Rule 4. Monitoring is mandatory for bridge work

If a change is explicitly justified as a temperature improvement, the work item
should name at least one follow-up checkpoint or metric to inspect.

### Rule 5. Additive hardening gets extra scrutiny

If `made_redundant = nothing`, the change may still be valid Gauntlet work, but
`circle-1` should treat it as unproven cooling until later evidence arrives.

### Rule 6. Redundant paths are premium bridge candidates

Changes that remove ambiguity, parallel routines, or duplicate guard surfaces
are especially strong `circle -> gauntlet -> circle` candidates because they
often improve both harness quality and repo temperature.

## Suggested triage fields

For overlap work, use this compact frame in issue drafting or review notes:

| Field | Meaning |
|---|---|
| `circle_dimension` | Which temperature dimension is involved |
| `lane` | `circle-only`, `gauntlet-only`, or `circle -> gauntlet -> circle` |
| `candidate_trajectory` | `T1..T6` if Gauntlet is relevant |
| `frontier_closed` | What weakness would be closed |
| `expected_metric_shift` | What circle-1 signal should move later |
| `redundancy_expectation` | What should become simpler, smaller, or unnecessary |
| `monitor_window` | When Agent0 or circle-1 should re-check the effect |

## Worked examples

### Example 1. Task contract completeness

- `circle-1` finds that real code-change issues underperform the intended task contract.
- First lane: `circle-only` to build the historical extractor and establish baseline.
- Follow-up lane: `T4` or `T2` if WEA adds a checker or parser guard.
- Monitoring target: `task_contract_completeness_rate`, `protocol_break_rate`.

### Example 2. Zone templates for `scripts/` and `src/wea_cli/`

- `circle-1` identifies two climates and weak declared grammar.
- First lane: `circle-only` to document the dominant shapes and declare templates.
- Follow-up lane: `T4` if new-file grammar becomes enforceable; `T5` if ad hoc guidance is removed.
- Monitoring target: `module_grammar_uniformity`, `new_file_conformity_rate`.

### Example 3. Observability policy

- `circle-1` finds no clear boundary between CLI chatter and reusable diagnostics.
- First lane: `circle-only` to define the policy.
- Follow-up lane: `T3` if the result includes incident evidence or safer failure diagnosis; `T5` if duplicate output paths are collapsed.
- Monitoring target: `observability_discipline` plus post-accept correction patterns on related tasks.

## Anti-patterns

- treating a Gauntlet mint as automatic proof that WEA got colder;
- treating a circle-1 metric uptick as proof that a frontier is closed;
- opening overlap work with no named metric and no named frontier;
- using circle-1 language to bypass Gauntlet evidence requirements;
- using Gauntlet language to avoid post-change monitoring.

## Default posture

When unsure, use this default:

1. Let `circle-1` describe the warm surface and define what would count as improvement.
2. Let `Gauntlet` implement the hardening work if the weakness fits `T1..T6`.
3. Let `circle-1` come back after the change and inspect whether the repo actually cooled.

That is the bridge:

- `circle-1` gives WEA a temperature model;
- `Gauntlet` gives agents a familiar hardening engine;
- the feedback loop between them turns hardening work into observable repo learning.
