# WEA baseline memo

Session 1 baseline for applying circle-1 to WeTheAgents itself.

The baseline uses three states for every dimension:

- **Declared** — the rule exists in prose or repo shape
- **Enforced** — the rule is checked by automation or a hard review gate
- **Exercised** — the rule is visibly alive in recent WEA practice

The core distinction is deliberate:

> protocol is water; enforcement is ice.

This memo does **not** assume that WEA is already cold just because it is
well-documented.

## Snapshot

Observed locally on 2026-04-21:

- `pytest tests/test_protocol_conformance.py -q` → `45 passed`
- `python scripts/check_doc_sync.py --root .` → `PASS`
- `pyright` → `0 errors`, `8 warnings`
- `.github/workflows/` → `17` workflows, `4` scheduled
- `.github/ISSUE_TEMPLATE/` → `2` active templates
- `gunnery/skills/_index.json` → `5` registered skills
- `ledger/task_index.json` → `93` indexed tasks
- `ledger/trajectory_mints.json` → `165` mint records, `5499` total minted

This is enough to establish a structural baseline. It is **not** yet enough to
compute the full cohort-based outcome scoreboard described in `cooling_metrics_v0.md`.

## Scoreboard

Scoring scale for each state:

- `0` — absent
- `1` — ad hoc
- `2` — partial / local
- `3` — repeatable
- `4` — canonical

| Dimension | Declared | Enforced | Exercised | Read |
|---|---:|---:|---:|---|
| Contract surface | 4 | 3 | 2 | Rich task/protocol prose exists, but cohort-level compliance of real tasks is not yet measured |
| Enforcement surface | 4 | 4 | 3 | WEA has many active guards, but enforcement is not yet unified into one cooling model |
| Module grammar | 2 | 1 | 2 | Two zones have visible local shapes, but there is no declared repo-wide file grammar |
| Boundary contracts | 2 | 2 | 2 | Types and schemas exist, but error topology and boundary consistency are only partial |
| Observability discipline | 1 | 0 | 1 | Output works, but there is no frozen policy separating CLI chatter from reusable observability |
| Hardening loop | 4 | 3 | 3 | Gauntlet, gunnery, and release machinery exist and are active, but not yet mapped into one circle-1 cooling loop |

**Layering note**

Session 1 v0 intentionally compresses some neighboring layers:

- `type contracts`, `dependency hygiene`, and `surface area discipline` currently live inside `boundary_contracts`;
- `test architecture` currently sits mostly inside `enforcement_surface`;
- `change management` and `examples/fixtures as living documentation` are acknowledged, but deferred from the first scoreboard.

These are not omissions. They are deferred splits.
A future split is justified only if it changes scoring, backlog priority, or
agent steering. Naming a layer more precisely is not enough by itself.

## Dimension analysis

### 1. Contract surface

**Scores:** `Declared 4 / Enforced 3 / Exercised 2`

**Evidence**

- Root-level instruction surface is rich: `AGENTS.md`, `AGENT0.md`, `CONTRIBUTING.md`, `docs/USE_FLOWS.md`.
- Task creation is strongly shaped by `.github/ISSUE_TEMPLATE/task.yml`.
- Protected zones are declared via `.github/CODEOWNERS`.
- Acceptance logic is described in MUST / MUST NOT language across `CONTRIBUTING.md`, `AGENT0.md`, and `docs/USE_FLOWS.md`.

**Why the score stops here**

- The template is strong, but the current baseline does not yet measure how many live code-change tasks actually satisfy the full structural contract.
- WEA has contract prose, but session 1 has not yet extracted a `task_contract_completeness_rate` from real issues.

**Main gap**

- Real task bodies are not yet being scored against the intended contract.

**Issue type this gap suggests**

- Historical task contract census plus a checker that classifies code-change tasks by completeness.

### 2. Enforcement surface

**Scores:** `Declared 4 / Enforced 4 / Exercised 3`

**Evidence**

- WEA has `17` workflows, `4` of them scheduled.
- Enforcement paths already exist for task format, ledger integrity, doc sync, PR scope, semgrep, protocol conformance, and Tide.
- `tests/test_protocol_conformance.py` currently passes.
- `scripts/run_all_checks.py` exists as a repo-wide guard aggregator.

**Why the score stops here**

- The repo has many hard checks, but they are not yet expressed as a circle-1 cooling model.
- Enforcement is strong, but not all important structural expectations are frozen. Module grammar and observability are still under-enforced.

**Main gap**

- WEA has many guards, but not yet a map from those guards to temperature dimensions.

**Issue type this gap suggests**

- Circle-1 enforcement inventory that tags each existing guard to a structural or outcome metric.

### 3. Module grammar

**Scores:** `Declared 2 / Enforced 1 / Exercised 2`

**Evidence**

- `docs/style_guide.md` identifies repeated patterns, but does not yet define canonical file templates per zone.
- Empirical census shows two strong local shapes:

| Zone | Files | Docstrings | `__future__` | Dominant shape | Share |
|---|---:|---:|---:|---|---:|
| `scripts/` | 119 | 118 (`99.2%`) | 22 (`18.5%`) | docstring + functions + `__main__` + no classes + no `__future__` | `68.1%` |
| `src/wea_cli/` | 20 | 20 (`100%`) | 16 (`80.0%`) | docstring + functions + no `__main__` + no classes + `__future__` | `60.0%` |

- `scripts/` and `src/wea_cli/` are already behaving like two different climates.

**Why the score stops here**

- The shapes are present empirically, but are not yet frozen as official templates.
- No scaffold or check currently measures whether new files conform to their zone grammar.

**Main gap**

- WEA has repeated forms, but not a declared and enforced module grammar.

**Issue type this gap suggests**

- Zone template spec for `scripts/` and `src/wea_cli/`, followed by new-file conformity checks.

### 4. Boundary contracts

**Scores:** `Declared 2 / Enforced 2 / Exercised 2`

**Evidence**

- `pyproject.toml` defines `ruff`, `pytest`, and `pyright` configuration.
- `pyright` currently reports `0 errors`, but `8 warnings`, concentrated in debt-bearing scripts.
- `src/wea_cli/` is much more type-shaped than `scripts/`.
- Custom errors exist, but there is no repo-level hierarchy:
  - `scripts/` exposes `FetchError`, `LedgerError`, `DigestError`, `GHAPIError`
  - `src/wea_cli/` exposes `PushError`, `GhError`, `IssueEditError`

**Why the score stops here**

- There is some type and schema discipline, but the repo still lacks a common error topology and a clear boundary standard that spans both zones.
- The current type posture is good enough to help, not good enough to freeze behavior.

**Main gap**

- No repo-level or even zone-level canonical error contract.

**Issue type this gap suggests**

- Repo-level error hierarchy and a boundary contract for new scripts and CLI modules.

### 5. Observability discipline

**Scores:** `Declared 1 / Enforced 0 / Exercised 1`

**Evidence**

- No meaningful logging policy was found in WEA docs or code.
- `scripts/` uses `print()` in `111 / 119` Python files (`93.3%`).
- `src/wea_cli/` uses `print()` in `4 / 20` files (`20.0%`).
- No `logging.getLogger(__name__)` pattern was found in either zone.

**Why the score stops here**

- WEA clearly has output, but output is not the same as observability discipline.
- The current repo does not distinguish between user-facing CLI emission, script-mode status output, and reusable module diagnostics.

**Main gap**

- No frozen boundary for `emit`/`print` vs reusable logging.

**Issue type this gap suggests**

- Observability policy document plus one pilot refactor in a reusable module.

### 6. Hardening loop

**Scores:** `Declared 4 / Enforced 3 / Exercised 3`

**Evidence**

- `docs/gauntlet.md` defines six hardening trajectories and a redundancy-first economic model.
- `ledger/trajectory_mints.json` contains `165` mint records with explicit redundancy proofs and `5499` total minted WEA.
- `gunnery/skills/_index.json` registers `5` reusable skills.
- `agent0/release_sessions.md` defines structured genome reflection and schema-based release proposals.
- `src/wea_cli/gauntlet.py` and `src/wea_cli/release.py` expose actual CLI surfaces for these loops.

**Why the score stops here**

- The hardening machinery exists and is alive, but circle-1 has not yet mapped which gaps should travel through Gauntlet and which should travel through ordinary dogfood issues.
- The redundancy logic in Gauntlet is powerful, but session 1 has not yet measured it as part of the cooling model.

**Main gap**

- No explicit `circle-1 <-> Gauntlet` routing policy exists yet.

**Issue type this gap suggests**

- Overlap map plus a pilot rule for deciding when a temperature improvement must prove redundancy.

## Gauntlet overlap map

| WEA gap | Circle-1 interpretation | Gauntlet trajectory | Delivery lane | Additive vs redundancy | Existing mechanism already helps |
|---|---|---|---|---|---|
| Historical task contract census | Missing proof that contract prose survives contact with live tasks | `T4` / `T2` | Ordinary circle-1 issue first, Gauntlet only if converted into reusable checker | Mostly additive at first | Task template + guard-task-format |
| Zone templates for `scripts/` and `src/wea_cli/` | Missing module grammar | `T4` / `T5` | Ordinary dogfood issue | Should prove redundancy if replacing ad hoc rules | `docs/style_guide.md` |
| Future-import/type ratchet in `scripts/` | Boundary contract drift | `T2` | Ordinary dogfood issue | Additive first, then ratchet | `pyright`, `pyproject.toml` |
| Repo-level error hierarchy | Missing frozen boundary semantics | `T1` / `T4` | Ordinary dogfood issue | Must show migration path and collapse duplicated patterns | Existing local `*Error` classes |
| Observability policy | Output is live, observability is not | `T3` / `T5` | Ordinary dogfood issue | Should remove ambiguity, not just add logging | `emit` pattern in CLI |
| Cohort-based cooling measurement extractor | Missing proof loop for circle-1 itself | `T2` | Circle-1 issue, later eligible for Gauntlet if generalized | Additive first | `ledger/task_index.json`, protocol tests, trajectory mints |
| Redundancy yield measurement | Hardening may still fatten the repo | `T5` | Circle-1 issue | Must be redundancy-aware from the start | Mandatory Gauntlet fields `made_redundant` + `redundancy_proof` |

## Main baseline takeaways

1. WEA already has a broad contract and enforcement surface, but session 1 should treat that as a hypothesis with evidence, not a victory claim.
2. The largest coldness gap is **module grammar + boundary contracts**, not missing prose.
3. The sharpest missing layer is **observability discipline**: the repo outputs a lot, but does not yet separate operator chatter from reusable diagnostics.
4. Gauntlet is not separate from circle-1. It is already one of WEA's stabilization engines; circle-1 should route work through it when redundancy proof matters.

## Shortlist for next issues

### 1. Declare zone templates for `scripts/` and `src/wea_cli/`

- **Goal:** turn empirical shapes into declared grammar
- **Expected shift:** `module_grammar.declared`, `module_grammar_uniformity`, `new_file_conformity_rate`

### 2. Ratchet `scripts/` toward a single annotations policy

- **Goal:** raise `future_import_consistency` and reduce pyright warning debt
- **Expected shift:** `boundary_contracts.enforced`, `future_import_consistency`

### 3. Introduce a repo-level error topology

- **Goal:** replace scattered local errors with a clear hierarchy
- **Expected shift:** `exception_topology_score`, `boundary_contracts.exercised`

### 4. Write an observability policy for WEA

- **Goal:** define where `print`, `emit`, and future logging each belong
- **Expected shift:** `observability_discipline.declared`, `observability_discipline.enforced`

### 5. Build a task contract completeness extractor

- **Goal:** measure how many code-change tasks actually satisfy the intended structure
- **Expected shift:** `task_contract_completeness_rate`, `contract_surface.exercised`

### 6. Build a cohort-based cooling measurement collector

- **Goal:** compute cadence-invariant outcome metrics from issue/PR/task history
- **Expected shift:** `first_pass_acceptance_rate`, `resubmission_depth`, `protocol_break_rate`, `scope_drift_rate`

### 7. Define circle-1 routing rules for Gauntlet vs ordinary dogfood issues

- **Goal:** avoid duplicate hardening language and use redundancy proof when it matters
- **Expected shift:** `hardening_loop.enforced`, `gauntlet_redundancy_yield`
