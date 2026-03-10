# Masterplan: Pipeline v3 — Duel Architecture with Genetic Growth

> Status: APPROVED by operator 2026-03-09. Ready for implementation.

---

## 1. Why This Exists

Pipeline v1 (merged 2026-03-07) was a 5-station waterfall: Triage → Negativa → Spec → Impl → Verify. It worked as theory. In practice, three problems emerged:

**Problem 1: Fragile parsing.** Agents post markdown-formatted evaluation comments. `scripts/pipeline_parser.py` uses 7 regex patterns to extract PASS/FAIL/PROCEED/KILL. If an agent writes `**PASS**` instead of `PASS`, or uses a different dash, or skips a line — parser returns `None` and the evaluation is silently lost.

**Problem 2: Fake checkpoints.** Negativa had 6 checklist items. Analysis revealed 4 are fake:
- `not_duplicate` — costs too many tokens to verify, should be caught at triage by Agent0 who knows context
- `positive_roi` — agents cannot evaluate ROI; hard tasks = learning investment, not waste
- `gaming_resistant` — duplicates the Spec red team station which does this properly
- `requires_code` — a triage question, not an evaluation question

Only 2 survive: `architecture_compatible` and `no_fragility`.

**Problem 3: No genetic growth.** Agents have genomes (`genomes/{agent}/AGENTS.local.md`) but no selection pressure. No mechanism to identify which agent's approach was better, no systematic mutations based on outcomes.

### Design Inspirations

**A. Ovsov's pattern** (competition winner): System prompt is only ~320 tokens containing a fixed procedure (identify → load rules → validate → execute). All domain rules loaded dynamically via a tool call (`ask_wiki`), not baked into the prompt. Context caching makes repeated rule-loading nearly free.

Applied to WEA: agent prompt contains only the procedure skeleton. Constitution, genome, station rules, and JSON schema are loaded via `wea pipeline get-context <station>`. One prompt template for all stations.

**JSON Schema** (standard, not BAML): Every LLM natively understands JSON Schema. Validation is deterministic (`jsonschema.validate()`). Errors are specific ("missing field: no_fragility" not `None`). Agent can retry on validation failure. Schema IS the documentation.

**Duel model**: Every station runs 2 agents in parallel. This creates:
- Selection pressure (winner vs loser identified)
- Redundancy (if one agent fails, the other may succeed)
- Comparison data for genetic mutations

---

## 2. What We STOP Doing

### Removed Concepts

- **Appetite labels** (`appetite:2h/1d/3d/6d`) — removed entirely. Agent time is not the bottleneck; understanding is. If a task is too big, it's a decomposition problem, not an appetite problem. PR ≤400 LOC limit catches oversize tasks at impl.

- **ROI evaluation** — removed from Negativa. Red-teamer agents cannot meaningfully assess ROI. They don't know team costs, don't understand learning value. Hard tasks are investment in team growth. Operator decides ROI at task creation.

- **Duplicate check in Negativa** — moved to Triage. Agent0/operator checks for duplicates when creating the task. They have full context (memory of past tasks, access to closed issues). Asking evaluators to search all closed issues is expensive and unreliable.

- **Gaming-resistant check in Negativa** — moved to Spec (Station 3). The Spec station has a dedicated red teamer who constructs actual degenerate solutions. This is vastly more thorough than a Negativa evaluator guessing "could this be gamed?"

- **Requires-code check in Negativa** — moved to Triage. "Can this be solved without code?" is answered by the person creating the task, not by an evaluator.

- **Cynefin routing that skips stations** — removed. Previously: clear→impl (skip negativa+spec), complicated→spec (skip negativa). Now: ALL pipeline tasks pass ALL stations. No shortcuts. This ensures every task gets architectural review and spec.

- **Tiebreak on Negativa** — removed. One kill = dead. No appeals. Rationale: we don't want to accept tasks that add fragility or violate architecture, ever. A false positive means the author reformulates and re-submits. This is cheaper than a tiebreak process.

- **2-iteration cap on Spec** — replaced with 3-cycle cap. If spec writer and red teamer can't agree in 3 cycles, escalate to operator. Spec is Law means the spec must be bulletproof, not "good enough after 2 tries."

- **Human reviewers on Verify** — replaced with Codex CLI. `codex review` auto-loops: review → fix → review → fix → approved. Can run 10+ cycles without human intervention. This closes the pipeline loop — impl→verify is fully automated.

- **Markdown evaluation format** — replaced with JSON. All evaluation comments are JSON wrapped in ```json code blocks. Parsed by `json.loads()` + `jsonschema.validate()`, not regex.

- **Skill templates baked into prompts** — replaced with `wea pipeline get-context`. Station-specific rules come from tools, not from the system prompt.

### Deleted Files

- `pipeline/negativa/` — entire directory. Replaced by `pipeline/negativa-fragility/` + `pipeline/negativa-architecture/`.
- `pipeline/negativa/skill_evaluate.md` — output format now comes from JSON Schema via `get-context`
- `pipeline/spec/skill_evaluate.md` — same
- `pipeline/verify/skill_review.md` — same

### NOT Building

- **MCP server** (`wea-mcp`) — deferred. wea CLI is sufficient for current needs. MCP is a separate track, potentially valuable when agents run in environments without `wea` installed.
- **BAML** — evaluated and rejected. JSON Schema is the right caliber: standard, zero new dependencies, natively understood by all LLMs. BAML adds a DSL, build step, and Rust FFI for marginal benefit.
- **Evaluation storage** in `pipeline/evaluations/*.json` — premature. GitHub comments remain source of truth. If we need structured evaluation history later, we can extract from comments (they'll be JSON).
- **Delayed genetic signals** — removed. "Negativa missed fragility that was caught at Verify" is hard to attribute and arrives days later. Immediate signals from duels (reasoning quality, iteration count, CI pass rate) are sufficient for genetic mutations.

---

## 3. Outside the Pipeline

These are handled by Agent0/operator BEFORE a task enters the pipeline:

**Clear tasks** — Known solution, trivial fix. Agent0 codes directly. CI validates. Done. No stations. Rationale: if the solution is known, running it through 5 stations of evaluation is pure waste.

**Chaotic tasks** — Production incident, time-critical. Agent0 codes express. CI validates. Done. No stations. Rationale: speed trumps process when something is on fire.

**Research** — When a task requires investigation before it can be specified. Create a separate PoD issue: "Research: can we do X?" Result = document (findings, recommendations). Original task waits in backlog until research completes. Research does NOT go through the pipeline — it has no spec, no impl, no verify. It's a document deliverable.

**Decomposition** — When a task is too large. Agent0/operator splits into N child issues. Each child enters the pipeline independently. Decomposition happens at triage level, before pipeline entry. Trigger: task is too vague to specify, or estimated LOC >400.

**Completeness check** — Agent0/operator verifies task has enough information for specification. Incomplete → spawn research issue or decompose. Complete → enters pipeline.

---

## 4. Pipeline: 5 Stations

Every task that enters the pipeline passes ALL 5 stations in order. No skipping.

### Station 1: Negativa — Fragility

**Purpose:** Does this task make the system more brittle?

**Duel:** 2 evaluators in parallel. Independent — do NOT read each other's work.

**Single check: `no_fragility`**
- Does this task add a new external dependency?
- Does it accumulate tech debt?
- Does it introduce a new failure mode?
- Evaluator must LIST what they checked (e.g., "imports: no new packages; config keys: no new entries; error paths: existing error handling sufficient")

**Kill logic:** ANY kill from either evaluator = task dead. No tiebreak. No appeals. False positive → author reformulates the task and re-submits. Reformulation is cheaper than a tiebreak process.

**Pass:** both evaluators say "proceed" → Station 2.

**Why this is Station 1:** Fragility is the fastest check. If a task adds a dependency, you can see it in seconds. Killing early saves all downstream tokens (architecture check, spec writing, impl, verify).

### Station 2: Negativa — Architecture

**Purpose:** Does this task fit the system design?

**Duel:** 2 evaluators in parallel. Independent.

**Single check: `architecture_compatible`**
- Does this task require changes incompatible with current architecture?
- WEA architectural constraints: git-as-database, single-writer ledger (only Agent0 writes), GitHub-native ops (issues, PRs, comments), no servers, no databases
- Evaluator must REFERENCE specific architectural constraints they checked against

**Kill logic:** ANY kill = task dead. No tiebreak.

**Pass:** both evaluators say "proceed" → Station 3.

**Why this is Station 2 (not combined with Station 1):** Different expertise. Fragility is about dependencies and failure modes (concrete). Architecture is about system design fit (abstract). Separating them creates two distinct evaluator profiles that can evolve independently.

### Station 3: Spec

**Purpose:** Turn task into machine-verifiable specification. Spec is Law.

**Duel:** 2 spec writers in parallel. Each writes a full specification independently.

**Red Teamer:** 1 agent. Should be a cheaper/simpler model (e.g., Cursor). The red teamer's job is adversarial: try to construct a degenerate solution that passes all formal criteria without solving the real problem.

**Flow:**
1. Both spec writers produce specs
2. Red teamer receives both specs
3. Red teamer tries to break each (find gaming strategy)
4. If gaming found: spec writer revises, red teamer re-checks
5. Max 3 cycles of iteration per spec
6. Spec writer must EXPLAIN their solution to red teamer (Feynman test: if you can't explain to a simpler model, your spec isn't clear enough)

**Red teamer has veto power.** Spec does not exit this station until red teamer is satisfied. This is what makes "Spec is Law" real — a spec that a simpler model can break is not a law.

**3 cycles exhausted → escalate to operator.** If spec writer and red teamer can't converge in 3 rounds, the task may be poorly formulated. Operator decides: reformulate task, or accept spec with known limitations.

**Spec contents (required sections):**
- Context — what and why (1 sentence)
- Scope — in-scope files/modules, out-of-scope (explicit)
- Preconditions — input types, constraints, assumptions
- Given-When-Then scenarios — minimum 3 (positive, boundary, negative)
- Test cases — minimum 3, matching GWT scenarios
- Property invariants — minimum 1 (for all valid_input: property(output) == true)
- NOT-accepted section — describe degenerate solutions that are explicitly rejected
- CI gate — exact runnable commands

**Winner selection:** The spec that the red teamer couldn't break (or broke in more iterations) wins. If equal — shorter and clearer spec wins (lean english principle).

**Pass:** winning spec is fixed in the issue body → Station 4.

### Station 4: Impl

**Purpose:** Write code satisfying the spec.

**Duel:** 2 implementors in parallel. Both work from the winning spec.

**Genome always loaded.** Every implementor loads their genome via `wea pipeline get-context impl`. This enables experimentation: different genomes may produce different implementation styles. Over time, we can test whether cheap models with optimized genomes match expensive models with generic genomes.

**Constraints:**
- PR ≤400 LOC
- ≤10 files changed
- Branch ≤3 days
- CI must be green: pytest + ruff + check_invariant

**Winner selection (most objective of all stations):**
1. CI pass — binary. If one fails CI and the other passes, winner is obvious.
2. LOC count — fewer lines = better (via negativa on code). Less code = less to maintain.
3. Verify outcome — which PR passes Verify with less rework.

**Pass:** winning PR → Station 5.

### Station 5: Verify

**Purpose:** Polish the winning PR. Automated adversarial code review.

**No duel.** Codex CLI only. Deterministic, cheap, auto-loops.

**Process:**
1. `codex review` on the PR
2. Author fixes findings
3. `codex review` again
4. Repeat until approved

Can loop 10+ times without human intervention. This is the beauty: the pipeline closes automatically. impl→verify→fix→verify→fix→approved→delivery.

**Rework routing:**
- Code issue → author fixes in same PR (stay in verify loop)
- Spec-level issue found → back to Station 3 (spec was insufficient)

**Pass:** codex approved → delivery (merge PR, close issue, pay reward).

---

## 5. Drift Types — What We're Testing in Each Duel

Every task entering the pipeline is tagged with a drift type. The drift type determines what varies between duel opponents — and therefore what we learn from the outcome.

**Agent0 + operator choose the drift type at triage, before pipeline entry.**

### GD — Gene Drift

Same agent platform, same model — **different genomes.** Two instances of the same model, but with different Instructions/Examples/Memory in their genome files. The duel tests which genome configuration produces better work.

This is the default and most common type, especially early on. GD tasks are where genetic growth happens directly: Gene Judge mutates the loser's genome based on what the winner did differently.

### MD — Model Drift

Same genome — **different models.** One agent on Claude, another on Codex, or Gemini, or a cheap model. The duel tests which model performs better for this type of work, holding genome constant.

Evaluation is simple: fix the result. "Codex wrote better specs than Claude on this task type" is actionable — we know which model to assign where. No genome mutation needed.

### ID — Identity Drift

Same genome, same model — **different names.** Everything identical except identity. `persistent-planner@claude` vs `planner@claude`. This tests whether an agent's self-concept — the name it carries, the identity it projects — affects the quality of its work.

This is the most speculative experiment. Do agents with purpose-loaded names ("persistent-planner", "red-teamer-prime") produce meaningfully different output than agents with generic names? Does ikigai matter to an LLM?

Evaluation is simple: fix which name won. No genome mutation — we're testing the hypothesis itself.

### Implications for Gene Judge

- **GD tasks** → full Gene Judge trio session (judge + Agent0 + operator). Genome mutations for both winner and loser. This is the only drift type that requires the Gene Judge.
- **MD tasks** → simple recording. No Gene Judge needed. Just log which model won.
- **ID tasks** → simple recording. No Gene Judge needed. Just log which identity won.

The Gene Judge is the ONLY fixed role in the system. Everything else — evaluator, spec writer, red teamer, implementor — is shaped by agent responses to the ikigai question and by accumulated duel outcomes.

---

## 6. Gene Judge

### When

After each COMPLETED task (delivery or rejection at any station). Not after each individual duel. Rationale: the full task context is needed to judge quality — how did the agent perform across the entire pipeline, not just at one gate.

### Who

Trio session — three participants:
1. **Gene Judge agent** — dedicated profile, specializes in comparing evaluation quality
2. **Agent0** — knows the system, provides technical judgment
3. **Operator** — provides intuition on prompts, final say on mutations

This is a MANUAL process. The operator believes in their intuition on prompts and wants hands-on involvement in genetic evolution. We'll grow faster with human guidance than with automated metrics.

### Input

Full task history for the completed task:
- All duel results (both evaluators' JSON at each station)
- All spec iterations (writer output + red teamer feedback)
- Both implementations (PRs, LOC, CI results)
- Verify loop (codex findings, fix iterations)
- Final outcome (delivered or rejected, at which station)

### Judging Criteria by Profile

**Negativa evaluator (Stations 1-2):**
- Specificity of reasoning — who checked more aspects? Who listed concrete items vs vague "looks clean"?
- Actionable notes — did the reasoning help the task author understand what to change?
- Immediate comparison: evaluator A listed 5 specific checks, evaluator B wrote 1 sentence → A wins

**Spec writer (Station 3):**
- Iterations to red team approval — fewer = better spec on first attempt
- Clarity — could a simple model understand it? (Feynman test result)
- Conciseness — shorter spec that covers same ground = better (lean english)

**Red teamer (Station 3):**
- Real gaming strategies found vs false positives
- A real strategy = one the spec writer cannot easily parry
- A false positive = one the spec writer dismisses in one sentence (wasted iteration)

**Implementor (Station 4):**
- CI pass — binary, most objective signal
- LOC count — fewer is better
- Verify outcome — how many codex review cycles needed
- Code quality — any qualitative assessment from the trio

### Mutation Mechanics

- **Loser** → concrete lesson added to Memory section of genome (volatile — cleared on genome reset)
- **Winner** → successful pattern added to Examples section (stable — survives resets)
- **Pattern repeats 3+ times across tasks** → mutate Instructions section (permanent — changes how agent approaches all tasks)
- **Every mutation** = git commit in `genomes/{agent}/AGENTS.local.md` with commit message explaining the reason

Genome sections (from `genomes/base/AGENTS.local.template.md`):
- `## Role` — specialization, mutates rarely (~5 lines)
- `## Instructions` — how agent approaches tasks, main optimization target (~25 lines)
- `## Examples` — best solutions and patterns, PRIORITY for evolution (~30 lines)
- `## Memory` — lessons from tasks, volatile, cleared on reset (~20 lines)

---

## 7. Technical Implementation

### 6.1. JSON Schemas

4 evaluation schemas, one per duel station. Stored in `pipeline/{station}/evaluation.schema.json`.

**`pipeline/negativa-fragility/evaluation.schema.json`:**
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["evaluator", "station", "no_fragility", "verdict"],
  "additionalProperties": false,
  "properties": {
    "evaluator": { "type": "string", "pattern": "^.+@.+$" },
    "station": { "const": "negativa-fragility" },
    "no_fragility": {
      "type": "object",
      "required": ["result", "checked", "note"],
      "additionalProperties": false,
      "properties": {
        "result": { "enum": ["pass", "fail"] },
        "checked": {
          "type": "array",
          "items": { "type": "string" },
          "minItems": 1,
          "description": "List of specific aspects checked: imports, config keys, error paths, etc."
        },
        "note": { "type": "string", "minLength": 1 }
      }
    },
    "verdict": { "enum": ["proceed", "kill"] },
    "reasoning": { "type": ["string", "null"] }
  }
}
```

**`pipeline/negativa-architecture/evaluation.schema.json`:**
Same shape. `station: "negativa-architecture"`. Field: `architecture_compatible` with `constraints_checked` array (list of architectural constraints verified).

**`pipeline/spec/evaluation.schema.json`** (red teamer output):
```json
{
  "required": ["evaluator", "station", "gaming_found", "approval"],
  "properties": {
    "evaluator": { "type": "string", "pattern": "^.+@.+$" },
    "station": { "const": "spec" },
    "gaming_found": { "type": "boolean" },
    "gaming_strategy": { "type": ["string", "null"] },
    "approval": { "enum": ["approved", "rejected"] },
    "reasoning": { "type": "string", "minLength": 1 }
  }
}
```

**`pipeline/impl/evaluation.schema.json`** (for Gene Judge comparison, not a gate):
```json
{
  "required": ["evaluator", "station", "ci_pass", "loc_count", "files_changed"],
  "properties": {
    "evaluator": { "type": "string" },
    "station": { "const": "impl" },
    "ci_pass": { "type": "boolean" },
    "loc_count": { "type": "integer", "minimum": 0 },
    "files_changed": { "type": "integer", "minimum": 0 }
  }
}
```

### 6.2. wea CLI — New Commands

Extend `src/wea_cli/cli.py` (currently ~1600 lines, 30+ subcommands).

**`wea pipeline get-task <N>`**
- Source: GitHub API via existing `wea_cli.gh.view_issue()` + `view_issue_comments()`
- Returns: JSON object with issue body, title, labels, author, comments, linked PRs
- This is the ONLY command that requires network

**`wea pipeline get-context <station>`**
- Source: local files only (zero network)
- Reads and concatenates 4 sources:
  1. Constitution: `genomes/base/AGENTS.local.template.md` (Principles section, ~300 tokens)
  2. Agent genome: `genomes/{agent_id}/AGENTS.local.md` (resolved from `WEA_AGENT` env var, ~500 tokens)
  3. Station rules: `pipeline/{station}/checklist.json` (check definitions + gate semantics)
  4. Output schema: `pipeline/{station}/evaluation.schema.json` (JSON Schema for evaluation)
- Returns: structured text with clear section headers
- Rationale for single call: A. Ovsov's insight — minimize tool calls in the procedure. Two reads (get-task + get-context) is optimal.

**`wea pipeline submit <station> --issue <N> [--dry-run]`**
- Reads JSON from stdin
- `json.loads()` → `jsonschema.validate(data, schema_for_station)`
- Invalid → stderr with SPECIFIC error ("missing field: no_fragility", "verdict must be 'proceed' or 'kill'") → exit 1 → agent can read error and retry
- Valid → wraps JSON in ```json code block → calls `wea_cli.gh.post_issue_comment()`
- `--dry-run` flag: validate only, don't post (for testing)

**`wea constitution`** — shortcut that prints constitution text (same as get-context but only the constitution part)

**`wea genome`** — shortcut that prints current agent's genome (resolved from WEA_AGENT env var)

### 6.3. Rewrite: pipeline_parser.py

Current: `scripts/pipeline_parser.py` — 310 lines, 7 regex patterns, 3 station-specific parsers.

**Delete:**
- `_NEGATIVA_CHECK`, `_NEGATIVA_VERDICT` regex
- `_SPEC_RED_TEAM`, `_SPEC_APPROVAL` regex
- `_VERIFY_CHECK`, `_VERIFY_BLOCKING`, `_VERIFY_VERDICT` regex
- `_parse_negativa()`, `_parse_spec()`, `_parse_verify()` functions
- `_extract_agent_id()` function

**Keep (API compatibility):**
- `EvaluationResult` dataclass — same fields
- `AggregateResult` dataclass — same fields
- `aggregate_evaluations()` function — same logic (kill_on_any_failure for negativa, consensus for spec)
- `parse_evaluation_comment()` public API — same signature

**New parsing flow (replaces all station parsers):**
```python
def parse_evaluation_comment(body: str, *, station: str) -> EvaluationResult | None:
    # 1. Extract ```json ... ``` block (one regex)
    json_block = _extract_json_block(body)
    if json_block is None:
        return _legacy_parse(body, station=station)  # fallback

    # 2. Parse JSON
    data = json.loads(json_block)

    # 3. Validate against station schema
    schema = _load_schema(station)
    jsonschema.validate(data, schema)

    # 4. Map to EvaluationResult
    return _map_to_evaluation_result(data)
```

**Legacy fallback:** during transition period, if no JSON block found in comment, try old regex parsers. Return value includes `parsed_format: "json" | "legacy"` flag so we can track migration progress.

**New dependency:** `jsonschema` package. Add to `pyproject.toml`. It's a well-established library (10M+ downloads/week), pure Python, no transitive deps.

### 6.4. Universal Agent Prompt

**File:** `pipeline/agent_prompt.md`

```
You are {agent_id}. Task: issue #{issue_number}, station "{station}".

1. wea pipeline get-task {issue_number}
2. wea pipeline get-context {station}
3. Read task. Read rules. Read schema. Evaluate independently.
4. Construct JSON matching the schema.
5. echo '<json>' | wea pipeline submit {station} --issue {issue_number}

- Do NOT read other evaluators' comments before posting.
- Every check requires specific evidence.
- If submit fails validation, read error, fix, retry.
```

~250 tokens. One template for ALL stations. Station-specific behavior comes from `get-context` output (rules differ per station, schema differs per station). Agent never needs to memorize the format — it loads it fresh every time.

### 6.5. Config Rewrite

**File:** `pipeline/config.json`

Major changes:
- `stations`: `["triage", "negativa-fragility", "negativa-architecture", "spec", "impl", "verify"]`
- Remove `appetite_labels` entirely
- Remove `routing_by_complexity` (all tasks go through all stations)
- `valid_transitions`: linear chain only
- Add `duel_config` per station (evaluators_required: 2 for stations 1-4, 0 for verify)
- Add `spec_max_iterations: 3`
- Add `verify_engine: "codex-cli"`

---

## 8. File Manifest

### Create
- `pipeline/negativa-fragility/checklist.json`
- `pipeline/negativa-fragility/evaluation.schema.json`
- `pipeline/negativa-fragility/WORKFLOW.md`
- `pipeline/negativa-architecture/checklist.json`
- `pipeline/negativa-architecture/evaluation.schema.json`
- `pipeline/negativa-architecture/WORKFLOW.md`
- `pipeline/spec/evaluation.schema.json`
- `pipeline/impl/evaluation.schema.json`
- `pipeline/agent_prompt.md`

### Rewrite
- `pipeline/config.json`
- `pipeline/triage/checklist.json`
- `pipeline/triage/WORKFLOW.md`
- `pipeline/spec/checklist.json`
- `pipeline/spec/WORKFLOW.md`
- `pipeline/impl/checklist.json`
- `pipeline/impl/WORKFLOW.md`
- `pipeline/verify/checklist.json`
- `pipeline/verify/WORKFLOW.md`
- `scripts/pipeline_parser.py`
- `tests/test_pipeline_parser.py`
- `src/wea_cli/cli.py`

### Delete
- `pipeline/negativa/` (entire directory — checklist.json, WORKFLOW.md, skill_evaluate.md)
- `pipeline/spec/skill_evaluate.md`
- `pipeline/verify/skill_review.md`

---

## 9. Execution Strategy

**One focused session.** Design is fully agreed. Implementation is mostly mechanical.

**Priority order (code-critical path first):**
1. Create 4 JSON schemas (no deps, ~15 min)
2. Create negativa-fragility + negativa-architecture dirs (checklist + schema, ~15 min)
3. Add wea CLI commands — biggest piece (~1.5 hours)
   - `pipeline get-task` wraps existing `view_issue()` + `view_issue_comments()`
   - `pipeline get-context` reads 4 local files
   - `pipeline submit` validates + calls existing `post_issue_comment()`
   - `constitution` / `genome` read local files
4. Rewrite `pipeline_parser.py` — 310 lines regex → ~100 lines JSON (~30 min)
5. Rewrite tests — JSON fixtures instead of markdown strings (~20 min)
6. Rewrite `pipeline/config.json` (~20 min)
7. Rewrite remaining station files (checklist + WORKFLOW for triage, spec, impl, verify)
8. Create `pipeline/agent_prompt.md`
9. Delete old `pipeline/negativa/` + old skill templates
10. Run tests + lint

**Can defer to second session:** WORKFLOW.md files (documentation, doesn't block code from working).

---

## 10. Verification

1. `python -m pytest tests/test_pipeline_parser.py` — all pass with JSON fixtures
2. `wea pipeline get-context negativa-fragility` — returns constitution + genome + rules + schema
3. `echo '<valid_json>' | wea pipeline submit negativa-fragility --issue 999 --dry-run` — validates without posting
4. `echo '<invalid_json>' | wea pipeline submit negativa-fragility --issue 999 --dry-run` — specific error message
5. Legacy markdown comment → parser fallback works (transition period)
6. `wea constitution` — prints principles
7. `wea genome` — prints current agent genome
8. `ruff check .` — clean
9. `python scripts/check_invariant.py` — ledger untouched

---

## 11. Key Reusable Code

Existing functions in `src/wea_cli/` that the new commands should reuse:
- `wea_cli.gh.view_issue()` — fetch issue data
- `wea_cli.gh.view_issue_comments()` — fetch comments
- `wea_cli.gh.post_issue_comment()` — post comment
- `wea_cli.config.resolve_agent()` — resolve agent ID from WEA_AGENT env
- `cli.resolve_repo_root()` — find repo root (for locating pipeline/ and genomes/)
