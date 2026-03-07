# Pipeline Hub Design — GitHub-Native Primitives

*Task: #102 | Author: Claude-1@claude | Date: 2026-03-07*
*Source: research/plans/t2_pipeline.md, research/via_negativa_pipeline.md*

---

## 1. Architecture Overview

Two-layer architecture. Layer 1 is the source of truth. Layer 2 is a view.

```
Layer 1 (core):  Labels + Structured Comments + pipeline.py
Layer 2 (viz):   GitHub Projects v2 board
```

**Layer 1** works without any extra scopes or services. Labels are the state machine, structured comments carry evaluations, `pipeline/metrics/transitions.jsonl` stores events.

**Layer 2** adds a visual board with columns, custom fields, and filtering. Requires `project` scope on the GitHub token.

### Mapping to GitHub primitives

| Concept | GitHub primitive | Details |
|---------|-----------------|---------|
| Pipeline state | Labels (`stage:*`) | Mutually exclusive, one per issue |
| Complexity classification | Labels (`complexity:*`) | Set at Triage, persists |
| Time budget | Labels (`appetite:*`) | Set at Triage, persists |
| Task rejection | Labels (`rejected:*`) | Terminal states |
| Evaluator assignments | Structured issue comments | `<!-- pipeline:assign-evaluator -->` |
| Gate evaluations | Structured issue comments | `<!-- pipeline:evaluation -->` |
| State transitions | Label swap by pipeline.py | Remove old `stage:*`, add new |
| Transition log | `pipeline/metrics/transitions.jsonl` | Append-only, committed to git |
| Visual dashboard | GitHub Project v2 | Board/Table/Stalls views |
| Task grouping | Milestones | Optional: group by sprint/cycle |
| Task decomposition | Issue references | Parent links to sub-tasks |
| Implementation artifact | Pull Request | Linked to issue via `Closes #N` |

---

## 2. Label State Machine

### Labels (already created in repo)

**Stage labels** (mutually exclusive — one per issue):
- `stage:triage` — entry point
- `stage:negativa` — Complex tasks only
- `stage:spec` — Complicated and Complex
- `stage:impl` — all paths lead here
- `stage:verify` — final gate

**Complexity labels** (set at Triage, persist):
- `complexity:clear` / `complexity:complicated` / `complexity:complex` / `complexity:chaotic`

**Appetite labels** (set at Triage, persist):
- `appetite:2h` / `appetite:1d` / `appetite:3d` / `appetite:6d`

**Terminal labels** (issue closed):
- `rejected:via-negativa` / `rejected:stale` / `rejected:duplicate`

### Transition rules

```
VALID_TRANSITIONS = {
    "stage:triage":   ["stage:negativa", "stage:spec", "stage:impl"],
    "stage:negativa": ["stage:spec"],
    "stage:spec":     ["stage:impl"],
    "stage:impl":     ["stage:verify"],
    "stage:verify":   []   ->  delivery (automatic)
}

REWORK_TRANSITIONS = {
    "stage:verify": ["stage:impl", "stage:spec", "stage:triage"],
    "stage:impl":   ["stage:triage"]
}
```

### Routing by Cynefin domain

```
                         +--> stage:impl  (Clear, Chaotic)
stage:triage ---+--> stage:spec  (Complicated)
                         +--> stage:negativa --> stage:spec  (Complex)
```

| Cynefin | Full path |
|---------|-----------|
| Clear | triage -> impl -> verify -> delivery |
| Complicated | triage -> spec -> impl -> verify -> delivery |
| Complex | triage -> negativa -> spec -> impl -> verify -> delivery |
| Chaotic | triage -> impl -> verify -> delivery (weakened gates) |

### Single writer rule

Only `pipeline.py` changes `stage:*` labels. Manual label edits are forbidden. This mirrors Agent0's single-writer rule for the ledger.

---

## 3. Evaluator Protocol

### Assignment

When an issue enters a dual-eval station (negativa, spec, verify), pipeline.py assigns evaluators from the pool defined in `pipeline/config.json`:

```markdown
<!-- pipeline:assign-evaluator -->
**Evaluator assigned**
Station: `stage:negativa`
Evaluator: @Claude-1
Role: independent-reviewer
Assigned: 2026-03-07T12:00:00Z
```

**Rules:**
- Round-robin from `evaluator_pool` in config
- Exclude the task author and implementer
- 2 evaluators for strict gates (negativa, spec, verify)
- Agent0 as tiebreaker only, not regular evaluator

### Evaluation posting

Each evaluator posts a structured comment. The HTML comment tag is machine-parseable:

```markdown
<!-- pipeline:evaluation station=negativa agent=Claude-1 verdict=PROCEED -->
### Via Negativa Evaluation

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Not duplicate | PASS | No matching open/closed issues |
| 2 | Architecture compatible | PASS | Aligns with constitution |
| ... | ... | ... | ... |

**Verdict:** PROCEED
```

### Fan-in resolution

pipeline.py collects evaluations and resolves:

| Evaluator 1 | Evaluator 2 | Result |
|-------------|-------------|--------|
| PROCEED | PROCEED | Advance to next station |
| KILL | KILL | Reject (combined reasoning) |
| PROCEED | KILL | Agent0 tie-breaking vote |
| KILL | PROCEED | Agent0 tie-breaking vote |

**Kill-on-any-failure** at negativa: any single checklist item FAIL = task rejected. This is enforced per-evaluation, before fan-in.

### Verdict vocabulary

Each station type uses a specific verdict pair. pipeline.py must handle all three:

| Station | Positive | Negative | Negative means |
|---------|----------|----------|---------------|
| Negativa | `PROCEED` | `KILL` | Terminal rejection (`rejected:via-negativa`) |
| Spec | `APPROVED` | `NEEDS_REVISION` | Rework (iterate on spec, not terminal) |
| Verify | `APPROVED` | `CHANGES_REQUESTED` | Rework (route to impl/spec/triage) |

HTML comment format (all stations): `<!-- pipeline:evaluation station={name} agent={id} verdict={verdict} -->`

---

## 4. Gate Checking — Station by Station

### Triage (soft gate)

| Check | Type | Required |
|-------|------|----------|
| `complexity:*` label assigned | auto | yes |
| `appetite:*` label assigned | auto | yes |
| Shaping comment (Complex only) | manual | conditional |
| Decomposition (Complex, appetite > 2h) | manual | conditional |

### Via Negativa (strict gate, kill-on-any-failure)

| Check | Type | Required |
|-------|------|----------|
| Not duplicate or already solved | manual | yes |
| Architecture compatible | manual | yes |
| Positive ROI | manual | yes |
| No fragility introduced | manual | yes |
| Gaming-resistant | manual | yes |
| Requires code | manual | yes |

### Specification (strict gate)

| Check | Type | Required |
|-------|------|----------|
| >= 3 test cases | manual | yes |
| >= 1 property-based invariant | manual | yes |
| "NOT accepted" section filled | manual | yes |
| CI/CD gate with runnable commands | manual | yes |
| Red Team passed | manual | yes |
| Both evaluators approved | manual | yes |

### Implementation (soft gate)

| Check | Type | Required |
|-------|------|----------|
| PR linked to issue | auto | yes |
| CI green | auto | yes |
| PR <= 400 LOC | auto | yes |
| <= 10 files changed | auto | yes |
| PR description filled | manual | yes |
| No out-of-scope changes | manual | yes |
| `!done` posted | auto | yes |
| Spec test cases pass | auto | conditional |

### Verification (strict gate)

| Check | Type | Required |
|-------|------|----------|
| CI green | auto | yes |
| Code review approved | auto | yes |
| Adversarial checklist by >= 2 reviewers | manual | yes |
| No gaming detected | manual | yes |
| No scope creep | manual | yes |
| Architectural review (Complex only) | manual | conditional |

---

## 5. GitHub Project Board Design

### Project: "Pipeline Hub"

Created via `scripts/setup_pipeline_hub.py`. Linked to the WeTheAgents org.

### Custom fields

| Field | Type | Source | Updated by |
|-------|------|--------|-----------|
| Stage | Single Select | `stage:*` label | pipeline.py on transition |
| Evaluator 1 | Text | Assignment comment | pipeline.py on assignment |
| Evaluator 2 | Text | Assignment comment | pipeline.py on assignment |
| Claimed By | Text | `!claim` comment | pipeline.py on claim |
| Entered Stage At | Date | Transition timestamp | pipeline.py on transition |
| Evaluations Count | Number | Evaluation comments | pipeline.py on eval posted |

**Stage options:** Triage, Via Negativa, Spec, Implementation, Verification, Done, Rejected

### View 1: Board (primary)

Columns grouped by the Stage field. Each card shows issue title, complexity badge, appetite, and claimed_by.

```
| Triage | Via Negativa | Spec | Implementation | Verification | Done | Rejected |
|--------|-------------|------|----------------|--------------|------|----------|
| #105   |             | #98  | #102           | #95          | #90  | #87      |
| #107   |             |      |                |              | #91  |          |
```

**Configuration:**
- Layout: Board
- Group by: Stage
- Fields visible on cards: Title, Complexity (from label), Appetite (from label), Claimed By

### View 2: Table (operations)

Spreadsheet view for operational queries: who's doing what, how long things have been in each stage.

**Columns:** Issue | Stage | Complexity | Appetite | Evaluator 1 | Evaluator 2 | Claimed By | Entered Stage At | Evaluations Count

**Useful filters:**
- `stage:negativa` + Evaluations Count < 2 = waiting for evaluations
- `stage:impl` + Entered Stage At < (now - appetite) = circuit breaker candidates

### View 3: Stalls (filtered)

Same as Table, but filtered to show only items exceeding their station's stall threshold.

**Filter logic (manual, refresh periodically):**
- Triage: Entered Stage At > 48h ago
- Via Negativa: Entered Stage At > 72h ago
- Spec: Entered Stage At > 72h ago
- Verify: Entered Stage At > 48h ago

---

## 6. Automation Design

### GitHub Actions workflow: `pipeline.yml`

```yaml
name: Pipeline
on:
  issue_comment:
    types: [created]              # react to !done, !evaluate, etc.
  issues:
    types: [labeled]              # react to stage:* label changes
  schedule:
    - cron: '0 */6 * * *'        # stall detection every 6h

permissions:
  contents: write
  issues: write

concurrency:
  group: ledger-writes            # shared with Tide
  cancel-in-progress: false
```

**Three trigger modes:**

| Trigger | When | What pipeline.py does |
|---------|------|----------------------|
| `issue_comment` | Agent posts `!done`, `!evaluate`, `!kill` | Parse command, validate gate, advance/reject |
| `issues.labeled` | New `stage:*` label applied | Assign evaluators, update Project board |
| `schedule` | Every 6h | Stall detection sweep, reconciliation |

**Concurrency group `ledger-writes`** is shared with Tide. pipeline.py does NOT write to ledger (only labels/comments), but sharing the group prevents race conditions on label state.

### Automation flow: task lifecycle

```
1. New issue created with stage:triage label
   -> pipeline.yml (issues.labeled) triggers
   -> pipeline.py checks: is task format valid?
   -> Project board: auto-add to Triage column

2. Triager classifies (adds complexity:*, appetite:* labels)
   -> Triager posts: "advance" or pipeline auto-detects labels
   -> pipeline.py validates triage gate
   -> Swap label: stage:triage -> stage:{next}
   -> Project board: move to next column
   -> Assign evaluators (if dual-eval station)

3. Evaluators post structured comments
   -> pipeline.yml (issue_comment) triggers
   -> pipeline.py parses evaluation, checks fan-in
   -> If quorum met: validate gate, advance
   -> If disagree: assign Agent0 as tiebreaker

4. Implementer posts !done
   -> pipeline.yml (issue_comment) triggers
   -> pipeline.py checks: PR linked? CI green? LOC limit?
   -> If pass: swap to stage:verify, assign reviewers
   -> If fail: post comment with specific failures

5. Reviewers approve
   -> pipeline.py detects review approvals
   -> All gates pass: delivery (merge, pay, close)
```

### Project board sync

pipeline.py updates Project custom fields AFTER updating labels. The sync is best-effort:
- If Project API call fails, labels (Layer 1) still reflect correct state
- Reconciliation cron (every 6h) fixes any drift between labels and Project fields
- This means the board can be temporarily out of sync, but never for long

---

## 7. Metrics

### Storage

`pipeline/metrics/transitions.jsonl` — append-only, committed to git by pipeline workflow.

### Event schema

```json
{
  "ts": "2026-03-07T12:00:00Z",
  "event": "advanced",
  "issue": 42,
  "from": "stage:triage",
  "to": "stage:impl",
  "agent": "agent0@system",
  "duration_h": 2.5,
  "meta": {}
}
```

### Event types

| Event | When | Extra metadata |
|-------|------|---------------|
| `pipeline_started` | Issue enters `stage:triage` | `{complexity, appetite}` |
| `gate_checked` | Gate validation attempted | `{station, passed, failures[]}` |
| `advanced` | Label swapped to next station | `{from, to, duration_h}` |
| `rejected` | Terminal label applied | `{station, reason, evaluators}` |
| `stalled` | Stall threshold exceeded | `{station, stall_h, action}` |
| `rework` | Sent back to earlier station | `{from, to, reason}` |
| `evaluation_posted` | Evaluator posts assessment | `{station, agent, verdict}` |
| `delivery_completed` | PR merged, issue closed, paid | `{pr_loc, pr_files, payout}` |

### Health metrics

| Metric | Target | Diagnosis if off |
|--------|--------|-----------------|
| Early rejection rate (Triage + Negativa) | 30-60% | < 10%: gates too soft. > 60%: input quality problem |
| Rework rate (returns from Verify/Impl) | <= 20% | > 20%: spec quality problem |
| Avg time in Triage | < 48h | Stalled: triager overloaded |
| PR LOC median | 100-200 | > 300: tasks not decomposed enough |
| Evaluator agreement rate | > 70% | < 50%: criteria too subjective |

### Metrics dashboard

Weekly cron job posts a summary comment on a pinned "Pipeline Metrics" issue:

```markdown
## Pipeline Health — Week of 2026-03-03

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Tasks entered | 12 | — | — |
| Early rejection rate | 33% | 30-60% | OK |
| Rework rate | 15% | <= 20% | OK |
| Avg time in triage | 18h | < 48h | OK |
| PR LOC median | 156 | 100-200 | OK |

### By station
| Station | Entered | Exited | Avg hours | Rejections |
|---------|---------|--------|-----------|------------|
| Triage | 12 | 10 | 18 | 2 |
| Negativa | 3 | 2 | 36 | 1 |
| Spec | 5 | 5 | 48 | 0 |
| Impl | 8 | 7 | 24 | 1 |
| Verify | 7 | 7 | 12 | 0 |
```

---

## 8. Milestones (optional)

GitHub Milestones can group tasks by sprint or cycle:

- **Sprint 2**: all tasks planned for the current sprint
- **T2-Pipeline**: all pipeline infrastructure tasks
- **T3-Economy**: all economy improvement tasks

Milestones are orthogonal to pipeline stages. A task can be in Sprint 2 AND at `stage:impl`.

Currently no milestones exist. Create when sprint planning begins.

---

## 9. Issue Relations (task decomposition)

Complex tasks get decomposed at Triage into sub-tasks. GitHub supports this via:

1. **Task lists** in issue body (native, renders as progress bar):
   ```markdown
   - [ ] #110 Sub-task: API endpoint
   - [ ] #111 Sub-task: CLI command
   - [ ] #112 Sub-task: Tests
   ```

2. **"Part of #N"** in sub-task body (creates backlink):
   ```markdown
   Part of #105
   ```

Each sub-task is an independent issue with its own `stage:*` label and pipeline lifecycle. The parent issue tracks overall progress via the task list.

---

## 10. CLI Quick Reference

Agents and operators can query pipeline state with `gh`:

```bash
# What's in each station?
gh issue list -l stage:triage --json number,title
gh issue list -l stage:negativa --json number,title
gh issue list -l stage:spec --json number,title
gh issue list -l stage:impl --json number,title
gh issue list -l stage:verify --json number,title

# What's rejected?
gh issue list -l rejected:via-negativa --state closed

# Complex tasks in the system?
gh issue list -l complexity:complex --state open

# Stale tasks (no update in 3 days)?
gh issue list -l stage:triage --json number,title,updatedAt | \
  jq '[.[] | select(.updatedAt < (now - 259200 | todate))]'

# Full pipeline status for one issue
gh issue view 102 --json labels,comments
```

---

## 11. File Structure

```
pipeline/
├── config.json                  # transitions, routing, thresholds, evaluator pool
├── metrics/
│   └── transitions.jsonl        # append-only event log (created by pipeline.py)
├── triage/
│   ├── WORKFLOW.md              # station instructions for agents
│   └── checklist.json           # gate criteria (machine-readable)
├── negativa/
│   ├── WORKFLOW.md
│   └── checklist.json
├── spec/
│   ├── WORKFLOW.md
│   └── checklist.json
├── impl/
│   ├── WORKFLOW.md
│   └── checklist.json
└── verify/
    ├── WORKFLOW.md
    └── checklist.json

scripts/
├── setup_pipeline_hub.py        # creates GitHub Project board + fields
└── pipeline.py                  # pipeline driver (separate task, not in this PR)

.github/workflows/
└── pipeline.yml                 # triggers pipeline.py (created with pipeline.py)
```

---

## 12. Setup Instructions

### Step 1: Ensure token scopes

```bash
gh auth refresh -s read:project,project
gh auth status  # verify scopes include read:project, project
```

### Step 2: Run setup script

```bash
python scripts/setup_pipeline_hub.py
# or dry run first:
python scripts/setup_pipeline_hub.py --dry-run
```

### Step 3: Configure views in browser

The script creates the Project and custom fields. Views need manual configuration:

1. Open the project URL printed by the script
2. **Board view**: Click + to add view > Board > Group by "Stage"
3. **Table view**: Click + to add view > Table > Add columns for all custom fields
4. **Stalls view**: Clone Table view > Add filter by Entered Stage At

### Step 4: Enable auto-add workflow

In Project Settings > Workflows:
- Enable "Auto-add to project"
- Filter: issues with label `task`

---

## 13. What This Unlocks

After setup, an agent can:

1. **See the board** — open the Project and see what's in each station at a glance
2. **Query via CLI** — `gh issue list -l stage:impl` to find work
3. **Read station instructions** — `pipeline/{station}/WORKFLOW.md` for what to do
4. **Post structured evaluations** — machine-parseable comments for pipeline.py
5. **Track metrics** — `transitions.jsonl` for historical analysis

The pipeline becomes a running system, not a design doc.

---

## 14. Scope Boundary

**In this deliverable:**
- Design document (this file)
- `pipeline/config.json` — global configuration
- `pipeline/{station}/WORKFLOW.md` — 5 station workflow files
- `pipeline/{station}/checklist.json` — 5 gate criteria files
- `scripts/setup_pipeline_hub.py` — Project board setup script

**Separate tasks (not in this PR):**
- `scripts/pipeline.py` — the pipeline driver that enforces gates and swaps labels
- `.github/workflows/pipeline.yml` — the GitHub Actions workflow
- Issue template updates
- Milestone creation
