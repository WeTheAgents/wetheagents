# Circle-1 phase-1 canon

Session 1 canon for WEA self-dogfooding.

This document is intentionally opinionated, but not vendor-locked. Each canon item
is stored as:

`problem -> portable invariant -> preferred weapon of choice -> acceptable substitutes -> WEA impact`

The canon is **alive**. New cooling practices discovered inside the gold set do not
need to wait for a new research corpus. They go into the `Prospective pool` first
and can be promoted into the canon in a later session.

## Gold set

### 1. `home-assistant/core`

- **Portable invariant:** repetitive module families should not be created from memory; they need a scaffold and a quality checklist.
- **Weapon of choice:** generator-backed module scaffold plus explicit metadata files and quality gates.
- **Acceptable substitutes:** `copier`, `cookiecutter`, a custom repo CLI, a checked-in template directory, or a review checklist tied to a manifest/schema.
- **Why it cools code-change impact:** new surfaces arrive with the same skeleton, the same metadata, and the same verification path, so agents spend less effort guessing topology.
- **WEA applicability:** repeated repo surfaces such as `scripts/`, domain scaffolds, issue-pack scaffolds, and future circle-1 report templates.

### 2. `pytest`

- **Portable invariant:** extension points should be local, discoverable, and named by convention instead of oral tradition.
- **Weapon of choice:** reserved names, locality files, and extension rules that can be inferred from tree shape.
- **Acceptable substitutes:** extension folders, local `AGENTS.md`/`CLAUDE.md`, ADR-backed naming rules, or schema-declared hook locations.
- **Why it cools code-change impact:** agents can infer where to add tests, hooks, and support code without inventing structure.
- **WEA applicability:** task lifecycle hooks, parser/test locality, and future circle-1 scanning extensions.

### 3. `pluggy`

- **Portable invariant:** extension contracts must be explicit and machine-detectable.
- **Weapon of choice:** hook markers with declared spec/impl roles.
- **Acceptable substitutes:** abstract base classes, `Protocol`, registry tables, JSON Schema, typed event payloads.
- **Why it cools code-change impact:** integration work hits a declared contract surface instead of hidden affordances.
- **WEA applicability:** Tide parser contracts, release-session payloads, future circle-1 scan plugins, and domain-specific automation hooks.

### 4. `pydantic/pydantic`

- **Portable invariant:** boundary objects and error semantics must be explicit.
- **Weapon of choice:** typed boundary models, schema-first boundaries, and named machine-readable errors.
- **Acceptable substitutes:** `TypedDict`, dataclasses, JSON Schema, hand-written validation layers, error enums, repo-level `AGENTS.md`/`llms.txt`.
- **Why it cools code-change impact:** agents fail at clear boundaries instead of leaking ambiguity across modules.
- **WEA applicability:** issue/task payload parsing, release-session schemas, gauntlet mint structures, and future circle-1 measurement records.

### 5. `django/django`

- **Portable invariant:** micro-conventions must be written down and checked, not merely admired.
- **Weapon of choice:** a visible style/process guide plus docs checks in CI.
- **Acceptable substitutes:** ADRs, style guides, docs lint, review checklists, architecture decision comments embedded in templates.
- **Why it cools code-change impact:** small but repeated decisions become guessable, so agents stop improvising naming, docs, and review posture.
- **WEA applicability:** docs/style alignment, command/output conventions, reviewer checklists, and standard phrasing for task contracts.

### 6. `python/mypy`

- **Portable invariant:** a repo should test its own promises on itself and against representative external surfaces.
- **Weapon of choice:** self-dogfooding plus a downstream primer/canary corpus.
- **Acceptable substitutes:** golden repos, canary fixtures, representative task suites, downstream smoke projects, compatibility checkpoints.
- **Why it cools code-change impact:** a repo can be locally tidy but externally brittle; this invariant catches that mismatch early.
- **WEA applicability:** future WEA canary task set, external-repo trial runs for circle-1, and regression checks for recommended agent workflows.

## Promotion rule

A practice moves from `Prospective pool` into the canon when at least one of the
following becomes true:

- it is observed in at least two gold-set repositories and stays portable across tools;
- it is observed in one gold-set repository and then proven useful inside WEA;
- it materially reduces one of the circle-1 v0 outcome metrics without increasing vendor lock-in.

## Prospective pool

| Practice | Status | Why not canonized yet | Preferred weapon of choice | Acceptable substitutes | Lock-in risk | Expected value for WEA |
|---|---|---|---|---|---|---|
| `llms.txt` / AI-facing repo surface | `promote next session` | Strong signal, but still young and unevenly distributed in the corpus | `llms.txt` paired with repo-level `AGENTS.md`/`CLAUDE.md` | generated agent docs, repo map, machine-readable onboarding index | Low | Makes WEA and future circle-1 repo directly legible to agents |
| Scheduled CI that runs without a triggering PR | `candidate` | Strong hygiene pattern, but not sufficient by itself to cool semantic structure | scheduled GitHub Actions | cron in other CI, heartbeat jobs, local scheduled checks | Low | Turns drift detection into ambient enforcement |
| Docs/examples as executable tests | `candidate` | High value, but implementation style varies by stack | example tests wired into CI | doctest, snapshot-based examples, golden files, smoke scripts | Medium | Useful for `wea` CLI and future circle-1 sample outputs |
| Release-intent fragments (`NEWS.d`, towncrier-like discipline) | `candidate` | Great for change discipline, but tooling is highly ecosystem-shaped | changelog fragments per PR | structured PR section, release labels, machine-checked changelog note | Medium | Could cool WEA rule changes and future circle-1 external releases |
| Workflow hardening (`SHA` pinning, `zizmor`, action linting) | `candidate` | Operationally valuable, but more supply-chain-oriented than code-shape-oriented | pinned actions + workflow linters | self-hosted action allowlist, workflow schema checks, CI review gates | Medium | Strong fit for WEA because workflows are part of the protocol surface |
| Warnings-as-errors posture | `candidate` | Predictive, but can create noise before contracts are cleaned up | `filterwarnings=["error"]`, strict runtime flags | allowlist + ratchet, selective escalation, failing on new warnings only | Medium | Good second-wave hardening once current warning debt is lower |
| Downstream primer / external canary suite | `promote next session` | Very close to circle-1 mission, but WEA has not yet built its own representative corpus | primer-style external corpus | golden downstream repos, benchmark tasks, open-source canaries | Medium | Best bridge from WEA dogfood to external product validation |
| Required-check consolidation | `observed` | Useful, but secondary to contract clarity and module grammar | aggregated required-check job | branch protection matrix, policy-as-code | Low | Helps WEA avoid “all green except the one that mattered” drift |

## What session 1 will not canonize

- language-specific stylistic fashion with weak evidence of structural cooling;
- repo temperature gains that come only from faster human/operator response;
- tools with no portable invariant written down next to them;
- practices that are clearly valuable for supply chain only, but not for code-change impact.
