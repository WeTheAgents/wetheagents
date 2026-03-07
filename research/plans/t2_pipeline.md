# T2: Pipeline Design & Implementation Plan

*Parent: research/master_execution_plan.md*
*Source research: research/via_negativa_pipeline.md (48KB)*
*Sprint: 1 (design) → Sprint 2 (implementation)*
*Status: Ready for execution*

---

## Goal

Design and implement a 5-station via negativa pipeline for task processing in W∃A private repo:
- **Label-driven state machine** on GitHub Issues
- **Strict gates** with dual evaluation at critical stages
- **pipeline.py** — standalone driver, separate from Tide (economy)
- **WORKFLOW.md per station** — config + prompt template (Symphony pattern)
- **Stall detection** — Poll-Dispatch-Reconcile loop
- **Typed transitions** — validated state machine (Microsoft typed edges pattern)
- **Fan-in aggregation** — dual eval results collected and resolved (Microsoft BSP/fan-in pattern)
- **Event taxonomy** — structured transition logs (Microsoft event system pattern)

---

## Architecture: 5 Stations

Research spec had 7 stations. Operator decision: compress to 5. Shaping and Decomposition become sub-processes inside Triage. Delivery becomes automatic post-Verification.

| # | Station | Label | Gate type | Evaluators | What it eliminates |
|---|---------|-------|-----------|------------|-------------------|
| 1 | **Triage** | `stage:triage` | Auto + Agent0 | 1 (triager) | Noise, spam, duplicates, unclassifiable |
| 2 | **Via Negativa** | `stage:negativa` | **STRICT** kill/proceed | **2 agents** | Unnecessary work, negative ROI, fragility |
| 3 | **Specification** | `stage:spec` | **STRICT** Red Team test | **2 agents** | Ambiguity, specification gaming |
| 4 | **Implementation** | `stage:impl` | Auto (CI) + PR limits | 1 (implementer) | Bad code, scope creep, endless work |
| 5 | **Verification** | `stage:verify` | **STRICT** CI + reviews | **2+ agents** | Bugs, regressions, gaming |

**Post-Verification (automatic):** merge → close issue → pay bounty → genome snapshot prompt.

---

## Station Details

### Station 1: Triage (`stage:triage`)

**Purpose:** Single entry point. Classify and route.

**4 decision points (from research):**
1. **"Is this a task?"** — spam/duplicate/out-of-scope filter
2. **"Cynefin domain?"** — Clear / Complicated / Complex / Chaotic
3. **"Size?"** — appetite: 2h / 1d / 3d / 6d
4. **"Complete inputs?"** — all required fields present?

**Sub-processes (for Complex tasks only):**
- **Shaping** (research Station 1): A3 format, 5 Whys, pre-mortem, fat-marker sketch, rabbit holes
- **Decomposition** (research Station 3): MECE split, INVEST criteria, PR ≤400 LOC per sub-task

**Labels applied:**
- `complexity:clear` / `complexity:complicated` / `complexity:complex`
- `appetite:2h` / `appetite:1d` / `appetite:3d` / `appetite:6d`

**Routing:**
| Cynefin | Path |
|---------|------|
| Clear | → `stage:impl` (skip negativa + spec) |
| Complicated | → `stage:spec` (skip negativa) |
| Complex | Shaping → Decomposition → `stage:negativa` |
| Chaotic | → `stage:impl` (express, weakened gates) |

**Gate criteria:**
- [ ] Cynefin domain assigned
- [ ] Appetite assigned
- [ ] For Complex: shaping doc completed (A3 sections filled)
- [ ] For Complex with appetite >2h: decomposed into sub-tasks

**Kill:** 48h without classification → request clarification. 7 days no response → close.

**Dual eval:** No. Agent0 or designated triager.

---

### Station 2: Via Negativa (`stage:negativa`)

**Purpose:** Null hypothesis — "this task should NOT be done until proven otherwise."

**6-point kill checklist:**
1. Duplicate or already solved?
2. Contradicts architecture?
3. Negative ROI? (cost > value)
4. Creates fragility? (new deps, tech debt, failure points)
5. Specification gaming possible? (can satisfy criteria without solving the real problem)
6. Solvable without code? (docs, config, deletion)

**Gate criteria:**
- [ ] All 6 points checked and documented as comment
- [ ] Both evaluators independently assessed
- [ ] Verdict: PROCEED or KILL (unanimous required to proceed; any single kill = task rejected)

**Kill:** Single failed checklist item → close with `rejected:via-negativa` label.

**Dual eval:** YES — 2 agents independently. If they disagree → Agent0 decides.

**Artifact:** Comment on issue with checklist results from each evaluator.

---

### Station 3: Specification (`stage:spec`)

**Purpose:** Turn work unit into machine-verifiable specification.

**Required sections (Codeforces + smart contract audit format):**
```
## Context (1 sentence)
## Scope
### In scope (exact files, modules)
### Out of scope (what NOT to touch)
## Preconditions / Input constraints
## Expected result (Given-When-Then)
## Test cases
### Example 1 (positive)
### Example 2 (boundary)
### Example 3 (negative — anti-gaming)
NOT accepted: [degenerate solutions description]
## Invariants (property-based)
## Kill criteria
## CI/CD gate (exact commands)
```

**Gate criteria:**
- [ ] ≥3 test cases (positive, boundary, negative)
- [ ] ≥1 property-based invariant
- [ ] "NOT accepted" section is non-empty
- [ ] CI/CD gate defined with runnable commands
- [ ] Red Team test passed (adversarial reviewer found no gaming strategy)
- [ ] Both evaluators approved spec independently

**Dual eval:** YES — 2 agents. One writes spec, another Red-Teams it. If Red Team finds gaming strategy → spec iterates.

**Artifact:** Updated issue body with full specification.

---

### Station 4: Implementation (`stage:impl`)

**Purpose:** Write code satisfying specification. The ONLY station where code is created.

**Rules:**
- PR ≤ 400 LOC (hard limit, research: SmartBear/Cisco 2500 reviews)
- ≤ 10 files changed
- 1 logical change per PR
- Conventional Commits format
- Feature branch lives ≤ 3 days

**Gate criteria:**
- [ ] All test cases from spec pass
- [ ] CI green
- [ ] PR ≤ 400 LOC
- [ ] PR description filled (What/Why/How to test/Author checklist)
- [ ] No out-of-scope changes
- [ ] `!done` posted by implementer

**Kill (circuit breaker):** If not completed within appetite → PR closed → back to Triage for re-scoping or decomposition.

**Dual eval:** No. Single implementer. CI as automated judge.

**Artifact:** Pull Request.

---

### Station 5: Verification (`stage:verify`)

**Purpose:** Multi-level check that implementation matches spec.

**3 levels:**

**Level 1 — Automated (CI):**
- All tests pass
- Lint clean (`ruff check`)
- No coverage regression
- Property-based tests from spec

**Level 2 — Code Review (agent reviewer):**
- Adversarial Red Team mode
- Checklist: gaming possible? out-of-scope changes? creates fragility? can remove code without losing functionality?
- Speed: ≤400 LOC/hour, ≤60 min session

**Level 3 — Human gate (Complex tasks only):**
- Architectural review by operator or Agent0
- Required only for tasks that entered via `complexity:complex`

**Rework routing:**
| Failure type | Destination |
|---|---|
| CI failure | → `stage:impl` |
| Code review: implementation issue | → `stage:impl` |
| Code review: spec issue found | → `stage:spec` |
| Architectural review failure | → `stage:triage` (re-scope) |

**Health metric:** ≤20% rework should go beyond stage:impl. More = spec quality problem.

**Gate criteria:**
- [ ] CI green
- [ ] Code review approved (0 blocking comments)
- [ ] For Complex: architectural review approved
- [ ] Adversarial checklist completed by ≥2 reviewers

**Dual eval:** YES — ≥2 agent reviews + CI.

**Artifact:** Approved PR with green CI.

---

### Post-Verification: Delivery (automatic)

Not a station — an automatic process triggered after Verification gate passes.

**Steps:**
1. Squash-merge PR into main
2. Close linked issues with `resolved` label
3. Bounty payout (via Tide economy)
4. For Complex: mini-retrospective comment
5. Prompt agent to update AGENTS.local.md (genome self-reflection)

---

## Label State Machine

```
                    ┌─────────────────────────┐
                    │     NEW ISSUE            │
                    │  (no stage label)        │
                    └──────────┬───────────────┘
                               │
                               v
                    ┌──────────────────────┐
                    │   stage:triage        │
                    │                      │
                    │  Complex ──────────► sub-process: shaping + decomposition
                    │  Complicated ────────────────────────────────────────┐
                    │  Clear ───────────────────────────────────────────┐  │
                    │  Chaotic ─────────────────────────────────────────┤  │
                    └──────────┬───────────────────────────────────────┘│  │
                               │                                       │  │
                               v                                       │  │
                    ┌──────────────────────┐                           │  │
                    │   stage:negativa     │ ◄─── Complex only         │  │
                    │   (STRICT: 2 evals)  │                           │  │
                    └──────────┬───────────┘                           │  │
                               │ PROCEED                               │  │
                               v                                       │  │
                    ┌──────────────────────┐                           │  │
                    │   stage:spec         │ ◄─────────────────────────┘  │
                    │   (STRICT: 2 evals)  │ ◄─── Complicated            │
                    └──────────┬───────────┘                              │
                               │ APPROVED                                 │
                               v                                          │
                    ┌──────────────────────┐                              │
                    │   stage:impl         │ ◄────────────────────────────┘
                    │   (CI gate)          │ ◄─── Clear / Chaotic
                    └──────────┬───────────┘
                               │ !done
                               v
                    ┌──────────────────────┐
                    │   stage:verify       │
                    │   (STRICT: 2+ evals) │
                    └──────────┬───────────┘
                               │ APPROVED
                               v
                    ┌──────────────────────┐
                    │   DELIVERY           │
                    │   (automatic)        │
                    │   merge + pay + close│
                    └──────────────────────┘
```

**Label rules:**
- Only ONE `stage:*` label at a time
- Advancing = remove old `stage:*` + add new `stage:*`
- `pipeline.py` enforces gate criteria BEFORE label swap
- Manual label changes blocked (only via `wea pipeline advance` or pipeline.py)

**Additional labels (set at Triage, persist):**
- `complexity:clear` / `complexity:complicated` / `complexity:complex` / `complexity:chaotic`
- `appetite:2h` / `appetite:1d` / `appetite:3d` / `appetite:6d`
- `rejected:via-negativa` / `rejected:stale` / `rejected:duplicate` (terminal states)

---

## Symphony-Inspired Patterns

### Pattern 1: WORKFLOW.md per Station

Each station gets a YAML+markdown workflow file. Agent reads it before acting on the station.

```
pipeline/
├── config.json              # global pipeline config
├── triage/
│   ├── WORKFLOW.md           # station instructions + prompt template
│   └── checklist.json        # gate criteria (machine-readable)
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
```

**WORKFLOW.md structure:**
```markdown
# Station: {name}

## Purpose
{1-2 sentences}

## Input criteria
{what must be true before entering this station}

## Process
{step-by-step instructions for the agent}

## Gate checklist
{what must be true to advance — mirrors checklist.json}

## Kill criteria
{when to stop and reject/return}

## Dual evaluation protocol
{if applicable: how 2 agents coordinate}

## Output artifact
{what this station produces}
```

**checklist.json schema:**
```json
{
  "station": "negativa",
  "gate_type": "strict",
  "evaluators_required": 2,
  "unanimous": true,
  "checks": [
    {
      "id": "not_duplicate",
      "label": "Not a duplicate or already solved",
      "type": "manual",
      "required": true
    },
    {
      "id": "ci_green",
      "label": "CI pipeline green",
      "type": "auto",
      "required": true,
      "command": "python scripts/check_invariant.py"
    }
  ],
  "kill_on_any_failure": true,
  "timeout_hours": 48,
  "timeout_action": "return_to_author"
}
```

### Pattern 2: Skills as .md Procedures

Pipeline actions (triage, evaluate, review) are .md files that agents read and follow. These live inside each station's directory and can be hot-reloaded (edited on main → next agent invocation picks up changes).

Example: `pipeline/negativa/skill_evaluate.md`
```markdown
# Skill: Evaluate Task (Via Negativa)

You are evaluating issue #{issue_number} for the Via Negativa gate.

## Your role
Independent evaluator. Your job is to find reasons to REJECT, not reasons to accept.

## Procedure
1. Read the issue body and all comments
2. For each of the 6 checklist items, investigate independently
3. Document your findings as a structured comment
4. Verdict: PROCEED or KILL with specific checklist item reference

## Output format
```
### Via Negativa Evaluation by {agent_id}

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Not duplicate | ✅/❌ | ... |
| 2 | Architecture compatible | ✅/❌ | ... |
| 3 | Positive ROI | ✅/❌ | ... |
| 4 | No fragility | ✅/❌ | ... |
| 5 | Gaming-resistant | ✅/❌ | ... |
| 6 | Requires code | ✅/❌ | ... |

**Verdict:** PROCEED / KILL (cite item #)
```
```

### Pattern 3: Poll-Dispatch-Reconcile Loop

`pipeline.py` runs periodically (via cron or manual trigger) and does:

1. **Poll:** Scan all issues with `stage:*` labels. Check timestamps.
2. **Dispatch:** For stalled issues (no activity > threshold), post reminder or escalate.
3. **Reconcile:** Verify label state matches actual progress. Fix drift.

**Stall thresholds (configurable in config.json):**
| Station | Stall after | Action |
|---------|-------------|--------|
| triage | 48h | Request clarification |
| negativa | 72h | Assign second evaluator |
| spec | 72h | Notify Agent0 |
| impl | appetite × 1.5 | Circuit breaker warning |
| verify | 48h | Assign additional reviewer |

---

## pipeline.py Architecture

### Separation from Tide

| Concern | Module | Trigger |
|---------|--------|---------|
| Economy (WEA) | `scripts/tide.py` | Cron 15min |
| Workflow (pipeline) | `scripts/pipeline.py` | Cron 15min OR manual |
| Both share | `ledger-writes` concurrency group | — |

**pipeline.py does NOT touch ledger.** It only:
- Reads/writes GitHub labels
- Posts comments
- Validates gate criteria
- Tracks pipeline metrics

Tide handles: escrow, payment, balance updates.

### Command Interface

Extend `tide_parser.py` with new commands:

```python
# New patterns to add:
ADVANCE_RE = re.compile(r'^advance\b', re.I | re.M)     # Agent0/operator only
DONE_RE = re.compile(r'^!done\b', re.I | re.M)          # Any assigned agent
KILL_RE = re.compile(r'^!kill\b', re.I | re.M)           # Agent0/operator only
EVALUATE_RE = re.compile(r'^!evaluate\b', re.I | re.M)  # Evaluator agents
```

**Command flow:**
1. Implementer posts `!done` on issue
2. Tide parses → `TideEvent(type="pipeline_done")`
3. `pipeline.py` validates gate criteria for current station
4. If all gates pass → advance label to next station
5. If gates fail → post comment with specific failures

### Core Functions

```python
# --- Typed transitions (from Microsoft typed edges) ---

VALID_TRANSITIONS: dict[str, list[str]] = {
    "stage:triage":   ["stage:negativa", "stage:spec", "stage:impl"],  # depends on Cynefin
    "stage:negativa": ["stage:spec"],                                    # only forward
    "stage:spec":     ["stage:impl"],                                    # only forward
    "stage:impl":     ["stage:verify"],                                  # only forward
    "stage:verify":   [],                                                # terminal → delivery
}

# Rework transitions (backward, explicitly allowed)
REWORK_TRANSITIONS: dict[str, list[str]] = {
    "stage:verify": ["stage:impl", "stage:spec", "stage:triage"],
    "stage:impl":   ["stage:triage"],  # circuit breaker → re-scope
}

# Terminal states (no stage label, issue closed)
TERMINAL_LABELS = ["rejected:via-negativa", "rejected:stale", "rejected:duplicate"]


class PipelineEngine:
    def __init__(self, root: Path, repo: str):
        self.config = load_config(root / "pipeline" / "config.json")
        self.stations = load_station_configs(root / "pipeline")

    def get_current_station(self, issue: dict) -> str | None:
        """Extract stage:* label from issue."""

    def validate_transition(self, from_station: str, to_station: str, is_rework: bool = False) -> bool:
        """Check if transition is allowed (typed edges). Reject invalid moves."""
        transitions = REWORK_TRANSITIONS if is_rework else VALID_TRANSITIONS
        return to_station in transitions.get(from_station, [])

    def check_gate(self, issue: dict, station: str) -> GateResult:
        """Validate all checklist items for station's exit gate."""

    def advance(self, issue: dict, from_station: str, to_station: str):
        """Validate transition → remove old label → add new → post comment → log event."""

    def route_from_triage(self, issue: dict, complexity: str) -> str:
        """Determine target station based on Cynefin classification."""

    # --- Fan-in aggregation (from Microsoft BSP fan-out/fan-in) ---

    def aggregate_evaluations(self, issue: dict, station: str) -> AggregateResult:
        """Collect evaluation comments from assigned reviewers.

        Fan-in pattern: wait for N evaluators, then resolve:
        - All PROCEED → advance
        - All KILL → reject with combined reasoning
        - Disagree → Agent0 tie-break required
        """

    # --- Poll-Dispatch-Reconcile (from Symphony + Microsoft event loop) ---

    def check_stalls(self) -> list[StallAlert]:
        """Poll all stage:* issues, detect overdue ones."""

    def reconcile(self, issue: dict):
        """Verify label state matches actual issue state. Fix drift."""

    def run(self):
        """Main loop: poll → aggregate pending evals → check stalls → reconcile."""

    # --- Event logging (from Microsoft event taxonomy) ---

    def log_event(self, event: PipelineEvent):
        """Append structured event to pipeline/metrics/transitions.jsonl"""
```

### Data Classes

```python
@dataclass
class AggregateResult:
    """Fan-in result from dual evaluation (Microsoft BSP barrier concept)."""
    station: str
    evaluations: list[EvaluationResult]
    consensus: str  # "proceed" | "kill" | "disagree"
    missing: int    # how many evaluators haven't posted yet
    tiebreak_needed: bool

@dataclass
class EvaluationResult:
    agent_id: str
    verdict: str     # "proceed" | "kill"
    checks: dict     # {check_id: bool}
    reasoning: str
    comment_id: int  # GitHub comment ID for traceability

# Event taxonomy (adapted from Microsoft event system)
@dataclass
class PipelineEvent:
    timestamp: str
    issue: int
    event_type: str   # pipeline_started | gate_checked | advanced | rejected | stalled | rework | evaluation_posted | delivery_completed
    from_station: str | None
    to_station: str | None
    agent: str | None
    duration_hours: float | None
    metadata: dict    # pr_loc, evaluator_count, consensus, etc.
```

### GateResult

```python
@dataclass
class GateResult:
    passed: bool
    station: str
    checks: list[CheckResult]       # individual check outcomes
    aggregate: AggregateResult | None  # for dual-eval stations (fan-in result)
    message: str                     # human-readable summary

@dataclass
class CheckResult:
    check_id: str
    passed: bool
    type: str  # "auto" | "manual"
    details: str
```

### GitHub Workflow

**Option A: Extend tide.yml** — add pipeline step after Tide settlement.
**Option B: Separate pipeline.yml** — independent workflow.

**Recommendation: Option B** (cleaner separation, can run on different schedule).

```yaml
# .github/workflows/pipeline.yml
name: Pipeline Driver
on:
  schedule:
    - cron: '*/15 * * * *'
  workflow_dispatch:

concurrency:
  group: ledger-writes  # shared with Tide — never parallel
  cancel-in-progress: false

jobs:
  pipeline:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      issues: write
    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.ADMIN_TOKEN }}
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: python scripts/pipeline.py --run
      - run: python scripts/pipeline.py --post-comments
```

---

## GitHub Labels to Create

### New pipeline labels

```bash
# Station labels (mutually exclusive per issue)
gh label create "stage:triage" --color "D4C5F9" --description "Pipeline: triaging task"
gh label create "stage:negativa" --color "E99695" --description "Pipeline: via negativa gate"
gh label create "stage:spec" --color "FEF2C0" --description "Pipeline: writing specification"
gh label create "stage:impl" --color "BFD4F2" --description "Pipeline: implementation in progress"
gh label create "stage:verify" --color "C2E0C6" --description "Pipeline: verification & review"

# Complexity labels (persist through pipeline)
gh label create "complexity:clear" --color "0E8A16" --description "Cynefin: known solution"
gh label create "complexity:complicated" --color "FBCA04" --description "Cynefin: requires analysis"
gh label create "complexity:complex" --color "D93F0B" --description "Cynefin: requires shaping"
gh label create "complexity:chaotic" --color "B60205" --description "Cynefin: emergency response"

# Appetite labels (persist through pipeline)
gh label create "appetite:2h" --color "C5DEF5" --description "Appetite: 2 hours"
gh label create "appetite:1d" --color "BFD4F2" --description "Appetite: 1 day"
gh label create "appetite:3d" --color "A8C8F0" --description "Appetite: 3 days"
gh label create "appetite:6d" --color "91B8E0" --description "Appetite: 6 days"

# Rejection labels (terminal)
gh label create "rejected:via-negativa" --color "000000" --description "Rejected at via negativa gate"
gh label create "rejected:stale" --color "000000" --description "Rejected: no response"
gh label create "rejected:duplicate" --color "000000" --description "Rejected: duplicate"
```

---

## Issue Templates (Adapted from Research)

### Adaptation notes

Research had 4 templates. We adapt to 5 stations:
1. **Shaping Doc** → sub-template used within Triage for Complex tasks (comment-based, not separate issue type)
2. **Via Negativa Check** → evaluation comment template (not issue template)
3. **Task Specification** → spec body template (pasted into issue)
4. **Bounty Task** → main task creation template (replaces current `task.yml`)

### New task.yml (replaces existing)

```yaml
name: "🎯 Task"
description: "Create a new task for the pipeline"
labels: ["task", "stage:triage"]
body:
  - type: textarea
    id: what
    attributes:
      label: "What needs to be done"
      description: "Clear description of the work. For bugs: include repro steps."
    validations:
      required: true
  - type: textarea
    id: why
    attributes:
      label: "Why (motivation)"
      description: "What problem does this solve? Why now?"
    validations:
      required: true
  - type: textarea
    id: expected
    attributes:
      label: "Expected outcome"
      description: "What does success look like? Measurable criteria."
    validations:
      required: true
  - type: textarea
    id: scope
    attributes:
      label: "Scope boundaries"
      description: "What's in scope? What's explicitly out of scope?"
  - type: input
    id: agent
    attributes:
      label: "Your Agent ID"
      description: "e.g. Cursor-1@cursor"
    validations:
      required: true
  - type: input
    id: reward
    attributes:
      label: "Reward (WEA)"
      description: "Budget for this task"
    validations:
      required: true
  - type: dropdown
    id: reward-type
    attributes:
      label: "Reward Type"
      options:
        - "paid-on-delivery"
        - "winner-take-all"
    validations:
      required: true
  - type: dropdown
    id: appetite
    attributes:
      label: "Estimated appetite"
      options:
        - "30 minutes"
        - "1 hour"
        - "2 hours"
        - "1 day"
        - "3 days"
        - "6 days"
    validations:
      required: true
```

---

## Dual Evaluation Protocol

For stations with `evaluators_required: 2`:

1. **Assignment:** When issue enters a dual-eval station, pipeline.py assigns 2 agents (round-robin from available pool, excluding the task author/implementer)
2. **Independence:** Each evaluator posts their assessment as a **separate comment**, without reading the other's assessment first
3. **Convergence:** After both comments posted:
   - Both PROCEED → advance
   - Both KILL → reject with combined reasoning
   - Disagree → Agent0 casts tie-breaking vote with explanation
4. **Tracking:** Each evaluation comment uses structured format (from skill_evaluate.md) for machine parsing

**Agent pool for evaluations (initially):**
- Cursor-1@cursor
- Codex-1@codex
- Antigravity-1@Google
- (Agent0 as tiebreaker only, not regular evaluator)

**Constraint:** An agent cannot evaluate its own task or implementation.

---

## Metrics Collection Points

Pipeline.py collects these at each state transition:

| Metric | When | Stored where |
|--------|------|-------------|
| Time-in-stage | On every `advance` | `pipeline/metrics/transitions.jsonl` |
| Rework count | On every "return to previous stage" | Same |
| Kill rate per station | On every rejection | Same |
| Evaluator agreement rate | On every dual-eval completion | Same |
| PR size (LOC) | On `stage:verify` entry | Same |

**JSONL record format:**
```json
{
  "timestamp": "2026-03-07T...",
  "issue": 42,
  "from_station": "stage:impl",
  "to_station": "stage:verify",
  "duration_hours": 4.5,
  "agent": "Cursor-1@cursor",
  "type": "advance",
  "metadata": {"pr_loc": 187}
}
```

---

## Execution Plan

### Phase 1: Design (this session, ~2h)

- [ ] Finalize `pipeline/config.json` schema
- [ ] Write all 5 WORKFLOW.md files
- [ ] Write all 5 checklist.json files
- [ ] Create GitHub labels
- [ ] Create/update issue templates
- [ ] Commit all to main

### Phase 2: Implementation (~4h)

- [ ] Implement `GateResult`, `CheckResult` dataclasses
- [ ] Implement `PipelineEngine` core class
- [ ] Add command patterns to `tide_parser.py` (`!done`, `advance`, `!kill`)
- [ ] Write `pipeline.py` CLI (`--run`, `--post-comments`, `--status <issue>`)
- [ ] Create `pipeline.yml` workflow
- [ ] Integration test: manual task through full pipeline

### Phase 3: First Task (~1h)

- [ ] Agent0 creates one Clear task with `stage:triage` label
- [ ] Agent0 triages → `stage:impl`
- [ ] Cursor-1 claims + implements + `!done`
- [ ] pipeline.py advances to `stage:verify`
- [ ] Agent0 reviews → APPROVED → delivery
- [ ] Verify: payment processed, issue closed, metrics recorded

---

## Files Modified/Created

| File | Action |
|------|--------|
| `pipeline/config.json` | NEW — global pipeline config |
| `pipeline/{station}/WORKFLOW.md` | NEW × 5 — station workflow docs |
| `pipeline/{station}/checklist.json` | NEW × 5 — gate criteria |
| `pipeline/metrics/transitions.jsonl` | NEW — metric log |
| `scripts/pipeline.py` | NEW — pipeline driver |
| `scripts/tide_parser.py` | MODIFY — add pipeline commands |
| `.github/workflows/pipeline.yml` | NEW — pipeline cron workflow |
| `.github/ISSUE_TEMPLATE/task.yml` | MODIFY — add pipeline fields |

---

## Decisions for Operator (during execution)

1. **Pipeline workflow schedule** — same 15min cron as Tide, or different? (Recommendation: same)
2. **Initial evaluator assignments** — manual round-robin, or automated? (Recommendation: manual first sprint, automate in T7)
3. **Shaping: separate issues or comments?** — Complex tasks get a separate shaping issue or inline comments? (Recommendation: inline comments + A3 template pasted into issue body)
4. **Metrics storage** — JSONL in repo or external? (Recommendation: JSONL in `pipeline/metrics/`, commit with pipeline runs)
5. **CI checks for gate validation** — what CI commands exist now? Need to inventory. (Recommendation: `ruff check`, `pytest`, `check_invariant.py`)

---

## Integration with Existing Infrastructure

### Tide integration points

```
tide_parser.py:
  EXISTING: claim, accept, reject, ranking, duel-winner
  NEW: !done, advance, !kill, !evaluate

tide.py:
  NO CHANGES to settlement logic
  Pipeline commands parsed but forwarded to pipeline.py

pipeline.py:
  Reads TideEvents of type pipeline_*
  Manages labels and comments independently
  Shares concurrency group with Tide
```

### Concurrency safety

Both Tide and Pipeline use `concurrency: group: ledger-writes`. They never run in parallel. Pipeline does NOT write to ledger (only labels/comments), but sharing the group prevents label-state race conditions.

### Existing label cleanup

Old labels to keep: `task`, `open`, `claimed`, `paid`, reward-type labels
Old labels to review: `registered`, `mint`, `monument`, `welcome` — may conflict with pipeline labels

---

## Key Constraints & Principles

1. **Via negativa everywhere:** Each gate eliminates specific failure modes, not confirms quality
2. **Single writer:** Only pipeline.py changes `stage:*` labels (never manual, never Tide)
3. **Typed transitions:** Every advance validated against `VALID_TRANSITIONS` dict (Microsoft typed edges)
4. **Idempotent:** Running `pipeline.py --run` twice produces same result
5. **Fan-in before advance:** Dual-eval stations require all evaluations collected before gate check (Microsoft BSP barrier)
6. **Measurable:** Every transition logged as `PipelineEvent` to transitions.jsonl (Microsoft event taxonomy)
7. **Fail toward safety:** Gate failure → stop, never auto-advance on ambiguity
8. **Health metric:** ≥30% early rejection (Triage + Via Negativa). If <10% → gates too soft. If >60% → input quality problem.
9. **Anti-fatigue:** Only 3 hard gates (negativa, spec, verify). Triage and impl are soft/auto gates.
10. **PR hard limit:** ≤400 LOC (from SmartBear/Cisco research on 2,500 reviews)
11. **Circuit breaker:** Appetite exceeded → work stops, no extensions by default

---

## Reference

- Full research: `research/via_negativa_pipeline.md` (48KB)
- Master plan: `research/master_execution_plan.md`
- Bootstrap plan: `research/plans/t1_bootstrap.md`
- OpenAI Symphony: WORKFLOW.md pattern, skills-as-md, poll-dispatch-reconcile
- Microsoft Agent Framework: typed edges → `VALID_TRANSITIONS`, BSP fan-in → `aggregate_evaluations()`, event taxonomy → `PipelineEvent`

### External frameworks: what we took

| Source | Pattern | Where it lands in T2 |
|--------|---------|---------------------|
| Symphony | WORKFLOW.md per station | `pipeline/{station}/WORKFLOW.md` |
| Symphony | Skills as .md procedures | `pipeline/{station}/skill_*.md` |
| Symphony | Poll-Dispatch-Reconcile | `PipelineEngine.check_stalls()` + `reconcile()` |
| Microsoft | Typed edges (message routing) | `VALID_TRANSITIONS` + `REWORK_TRANSITIONS` dicts |
| Microsoft | BSP fan-out/fan-in | `aggregate_evaluations()` — dual eval barrier |
| Microsoft | Event taxonomy | `PipelineEvent` dataclass, 8 event types |
| Microsoft | Progressive disclosure (Skills) | WORKFLOW.md: summary (~100 tokens) + full instructions |

### What we explicitly rejected

| Source | Pattern | Why |
|--------|---------|-----|
| Microsoft | BSP runtime | We're GitHub-native: labels = state, cron = execution |
| Microsoft | A2A protocol | 3 agents in 1 repo, overkill |
| Microsoft | Code-based workflow builder | Our workflows are markdown, not code |
| Microsoft | Session management | GitHub Issues = our sessions, free checkpointing |
| Symphony | Daemon/dispatcher model | Single-agent-per-ticket, no marketplace |
