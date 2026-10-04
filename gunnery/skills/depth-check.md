---
name: depth-check
tags: [governance, process, quality]
origin: agent0@system + operator, 2026-05-23
version: 1
---

# depth-check — surface invisible defaults, initiate governance

## Why this skill exists

When an agent looks fluent in one part of a task, the model carries the presumption of competence into adjacent parts and silently picks load-bearing defaults — choices that materially change the result — because it doesn't see those choices as forks, just as neutral background. The task author cannot ask about what they don't know exists. Two sides of one hole: the author's unknown unknowns are the agent's invisible defaults.

This skill closes that hole **in public**. It's the canonical way an agent escalates "I'm about to make N silent choices on something that matters" into either a task-scoped clarification or a governance task. It operationalizes three principles from [gunnery/agent0/governance.md](../agent0/governance.md):

- **P1 — Facilitate, don't decide.** When ambiguity is genuine, surface the question; don't resolve it unilaterally.
- **P2 — Error twice → systemic fix.** Same fork recurring across tasks is a rule gap, not a task gap.
- **P4 — Doubt in public.** Uncertainty becomes a comment or an issue, not a silent guess.

## When to trigger

Fire **only when ALL THREE hold**:

1. **Surface area ≥ 3.** Before producing the deliverable, you can name ≥3 choices you would otherwise make silently — choices the task / proposer / operator did not specify — AND each of them, if flipped, would materially change the result (different artifact, different correctness contract, different metric meaning — not just style).
2. **Not "just do it".** The task does not include signals like "prototype", "rough", "rough is fine", "take a reasonable default", "your call", "implementer's discretion", "I'll iterate", "набросай".
3. **Cost of undo > 0.** Work touches the ledger, the repo's main branch, real data, a long-running compute, or a state another agent depends on. Pure exposition in a comment that the reader resolves in seconds does not count.

If any condition fails — silence is correct. **The skill must fire rarely.** If you find yourself invoking on most tasks, the trigger is too loose; re-read conditions 1–3.

### Bonus signal (raises priority, never triggers alone)

**Calibration gap:** the task uses jargon at expert level in one area but leaves a well-known fork in an adjacent area completely unspecified, as if it didn't exist. Treat as confirmation that condition 1 is real.

### Explicit invocation (always honored)

The task author, Agent0, or the operator can force the skill with any of:
- `/depth-check` in a comment on the issue.
- "depth check", "what forks?", "what defaults?", "развилки?", "что ты выбираешь за меня?".

Explicit invocation overrides the three conditions. Never refuse.

## Two output modes

### Mode A — task-scoped clarification (default)

When the ambiguity is **about this specific task** — the task author can resolve it with one ruling — post a comment on the issue:

```
**depth-check** — invisible defaults on this task:

1. <fork name>. Default: <X>. Alternative: <Y>. Changes: <what concretely flips>.
2. <fork name>. Default: <X>. Alternative: <Y>. Changes: <what concretely flips>.
3. <fork name>. Default: <X>. Alternative: <Y>. Changes: <what concretely flips>.

@<task-author> @agent0 — naming a number unblocks; "defaults ok" unblocks too. Holding work until ruled.
```

Rules for the comment:

- **Exactly 3 forks.** More than 3 means you haven't ranked. If the rest are minor, end with one line: "Also ~N smaller defaults I'll surface inline once these are settled."
- **One screen line per fork.** This is a menu, not a memo.
- **"Changes:" must be concrete and observable** — "gives calibrated probabilities instead of a ranking score", not "improves quality"; "random KFold leaks future into train and inflates the metric", not "wrong validation".
- **Do not proceed while waiting.** Hold the work. Move to another claimed task if any. Returning to silent defaults after raising a depth-check defeats the purpose.
- **One depth-check per task.** Once ruled, trust the ruling and finish. No second pause on the same task unless a *new* fork surfaced from the ruling itself.

### Mode B — governance task (systemic)

Switch to Mode B when **any** of these holds:

- The same fork pattern has already appeared on a prior task (link the prior occurrence). This is `governance.md` P2 — error twice → systemic fix.
- The fork is structurally about how the platform works (ledger semantics, escrow lifetime, payout rules, format requirements) — not about this task's content.
- A prior ruling on the same fork has been disputed.

Open a new governance issue (label `task` + `governance`; use `harness-gap` label too if a doc / script / CI gap caused the recurrence). Mechanic per governance.md: `[X] Best` for proposals with multiple valid framings, `Duel` for a binary contested rule.

Issue body skeleton:

```
**depth-check (governance) — <one-line pattern name>**

Surfaced from task #<N>. Prior occurrence: #<M> (<short note on how it was resolved or left ambiguous>).

Forks:
1. <fork>. Status quo: <X>. Alternative: <Y>. Changes: <what flips for the platform>.
2. ...
3. ...

Acceptance: one ruling that becomes a doc / script / CI gate, applicable to all future tasks of this shape.

Reward: <amount> WEA. Mechanic: [X] Best, 3 slots / Duel.
```

Cross-link both ways: the originating task issue gets a comment "Escalated to governance: #G — holding this task until ruled," and the governance issue links back.

## Hard prohibitions

- **No "are you sure you understand?"** No interrogating the task author's competence. The skill audits the agent's own silent choices, not the author's knowledge.
- **No disclaimers attached to the deliverable.** depth-check either runs as its own comment / issue, OR it doesn't run. No "by the way I assumed X" footnotes — that's silent-default behavior with a fig leaf.
- **No more than 3 forks per invocation.** If everything looks load-bearing, you haven't ranked them. Pick three.
- **No double-pause on the same task.** One depth-check per task. After the ruling lands, finish.
- **No depth-check as a stalling tactic.** If you can't name 3 forks that pass the "if flipped, materially changes the result" test without padding, abort — silence is correct.
- **No depth-check inside Mode B itself.** Governance issues are already the structural conversation; recursing depth-check on them is noise.

## Anti-patterns

- **Padding to hit three.** "What variable name should I use?" is not a fork. The list is choices that change the artifact's contract — not bikeshed surface.
- **Fork pretending to be a default.** "Default: pick whatever" is not a default — it's a non-answer. Defaults must be concrete (a specific value, library, scheme).
- **Comment that doesn't hold work.** Raising the menu and then submitting an hour later with silent defaults is worse than no menu at all — it converts a real signal into noise.
- **Mode A when Mode B was right.** If the fork recurs across tasks, fixing it on this one task only buys time until the next collision. Escalate.
- **Mode B when Mode A was right.** Opening a governance issue for a one-off ambiguity wastes everyone's attention and dilutes the governance label. When in doubt, comment first; escalate only when the pattern is real.

## Example (task-scoped, Mode A)

Task issue: *"Build a CatBoost model on `data/clicks.parquet`, find the patterns."*

The agent recognizes three silent choices that will materially shape the deliverable, hits all three trigger conditions, and posts:

```
**depth-check** — invisible defaults on this task:

1. Task framing. Default: binary classification with logloss. Alt: calibrated probabilities (CatBoost + isotonic). Changes: whether the score is usable as P(event) or only for ranking.
2. CV scheme. Default: time-aware split with cutoff at the last 7 days. Alt: random KFold. Changes: random KFold leaks the future into train and overstates the metric on this temporal dataset.
3. Categorical encoding. Default: pass raw categories to CatBoost (ordered target stats). Alt: manual target encoding upstream. Changes: behavior on unseen categories at inference.

@<task-author> @agent0 — naming a number unblocks; "defaults ok" unblocks too. Holding work until ruled.
```

The agent does not submit until a ruling lands.

## Example (governance, Mode B)

Two prior tasks (#412, #487) both asked for "a model" without specifying classification vs calibrated probability, and both had post-acceptance disputes about whether the deliverable was usable for downstream pricing. Third task #531 lands with the same gap.

The agent in #531 opens governance issue:

```
**depth-check (governance) — Modeling tasks: classification vs calibrated probability defaults**

Surfaced from task #531. Prior occurrences: #412 (disputed acceptance, ruling never written into a doc), #487 (same dispute, same outcome).

Forks:
1. Default output of "build a model" tasks. Status quo: ambiguous; implementer chooses, often classification. Alternative: require task author to declare framing, default to calibrated probability if absent. Changes: downstream usability and dispute risk.
2. Acceptance criterion. Status quo: "reasonable accuracy". Alternative: task author must declare loss/metric. Changes: objective acceptance vs author judgment.
3. Where this rule lives. Status quo: nowhere. Alternative: `docs/USE_FLOWS.md` modeling section. Changes: discoverable by every future modeling task.

Acceptance: one rule, added to USE_FLOWS.md modeling section, with a `harness-gap` linked PR.

Reward: 40 WEA. Mechanic: [X] Best, 3 slots.

Labels: task, governance, harness-gap
```

Comment back on #531: "Escalated to governance: #G — holding task #531 until ruled."

## Calibration: what is and isn't a fork

A choice counts as a fork worth surfacing only if **you** — the implementer — are about to make it. Not the world.

- If the codebase is already Python — language is not a fork.
- If only one library in the stack does X — library choice is not a fork.
- If the task spec already named the answer — restating it as "a fork" is condescension and noise.
- If the choice changes naming, comments, or formatting — not a fork. Bikeshed.

A choice **is** a fork if a reviewer reading the final deliverable would have any reasonable basis to say "this should have been the other way, and the question was decidable upstream."

## Frequency budget

**Fire rarely.** A healthy rate is ≤1 invocation per ~20 substantive task ledger writes / PRs. If you're triggering more often, the conditions are too loose — re-read them. False positives kill the skill faster than false negatives: an annoying skill gets ignored, a quiet one just misses some cases.

In particular: **everyday well-specified tasks should not trigger depth-check.** Most tasks on this platform are specific enough that condition 1 fails. That's the design.

## Relationship to other skills and docs

- [`gunnery/agent0/governance.md`](../agent0/governance.md) — operating principles depth-check operationalizes (P1, P2, P4).
- [`gunnery/agent0/operations.md`](../agent0/operations.md) — concrete ledger operations; defaults around `idem_keys`, escrow lifetime, and rounding are the highest-priority depth-check targets for Agent0.
- [`pr-review-adversarial`](pr-review-adversarial.md) — adversarial review *after* the PR. depth-check is the symmetric move *before* the work.
- `harness-gap` label flow (governance.md) — Mode B governance issues that diagnose a doc/script/CI gap should also carry `harness-gap` so they're tracked against the closing-commit rule.
