# W∃A Private Repo: Master Execution Plan

*Created: 2026-03-07 by Agent0 + Operator*
*Status: Active — Sprint 0 complete, Sprint 1 ready*

## Context

Repo переходит в private. Это снимает три ограничения:
1. **Нет враждебных агентов** — убираем защитный overhead, ускоряем пайплайн
2. **Агенты общаются как удобно** — lean token language, сжатие → экономия → дорогие модели
3. **Полный контроль** — локальные worktree, генетика AGENTS.md, тотальная наблюдаемость

Цель: самая эффективная агентная команда разработки. Через генетическую эволюцию AGENTS.md + строгий via negativa пайплайн + сжатый язык коммуникации.

---

## 7 Tracks

| # | Track | Scope | Depends on | Sessions |
|---|-------|-------|------------|----------|
| T1 | **Bootstrap** | Worktrees, base AGENTS.md (7 принципов), AGENTS.local.md template | — | 1 |
| T2 | **Pipeline** ⚡ | 5 станций, strict gates, sub-stages, pipeline.py | — | 2 (deep dive) |
| T3 | **Genetics** | Версионирование промптов, метрики, отбор, мутации | T1, T2 | 2 |
| T4 | **Lean Language** | Исследование, словарь, бенчмарки сжатия | T1, T2 | 1-2 |
| T5 | **Antifragile** | Исследование паттернов, скоринг, рекомендации | — | 1 |
| T6 | **Observability** | 5 метрик, сбор, анализ | T2, T3 | 1 |
| T7 | **CLI Extensions** | Pipeline/genome/stats команды | T2, T3, T6 | 2 |

---

## Dependency Graph

```
T5 (Antifragile) ─── research, feeds into T2 & T6
       │                    │
       v                    v
T1 (Bootstrap) ──→ T2 (Pipeline) ──→ T3 (Genetics) ──→ T6 (Stats)
    │                   │                                    │
    └──→ T4 (Language)──┘                                    v
                                                         T7 (CLI)
```

**Critical path:** T1 → T2 → первая задача через пайплайн → T3 (первый snapshot fitness data)

---

## Execution Sequence (2 parallel chats)

### Sprint 0: Prep ✅
- Meta-plan (этот файл)
- Решение по ключевым развилкам
- Приватизация репо

### Sprint 1: Foundation

| Chat A: Bootstrap (T1) | Chat B: Pipeline Design (T2) |
|---|---|
| Worktrees для Codex, Cursor, Antigravity | Декомпозиция 5 станций (sub-stages внутри) |
| 7 базовых принципов → `genomes/base/AGENTS.md` | Label state machine (`stage:xxx`) |
| AGENTS.local.md template (Role/Instructions/Examples/Memory) | Gate criteria per station (JSON config) |
| Per-agent `.env`, git identity, WEA CLI config | Issue templates per station type |
| **Scope:** `genomes/`, agent worktree dirs, docs | **Scope:** `research/`, `.github/`, docs |

### Sprint 2: First Task Through Pipeline

| Chat A: Pipeline Implementation (T2→code) | Chat B: Genetics Foundation (T3) |
|---|---|
| Pipeline labels + issue templates in GitHub | AGENTS.local.md schema (4 секции) |
| `wea pipeline advance/status` (минимум) | `genomes/` directory + `genome_meta.json` |
| Pipeline driver: `scripts/pipeline.py` + workflow | Fitness function: какие метрики считать |
| **Первая реальная задача через пайплайн** | `wea genome snapshot` command |
| **Scope:** `scripts/`, `src/wea_cli/`, `.github/` | **Scope:** `src/wea_cli/`, `genomes/` |

### Sprint 3: Intelligence

| Chat A: Lean Language (T4) | Chat B: Stats + Antifragile (T5, T6) |
|---|---|
| Анализ реальных pipeline artifacts (из Sprint 2) | Antifragile research → scoring framework |
| Controlled vocabulary для pipeline communication | 5 метрик: throughput, rework, acceptance, cost, time-in-stage |
| `scripts/meaning_compression/` extension | Collection hooks в pipeline stages |
| Token savings benchmark | `wea stats` command |
| **Scope:** `scripts/`, docs | **Scope:** `src/wea_cli/`, stats files |

### Sprint 4: Evolution

| Chat A: Genetic Evolution (T3→impl) | Chat B: CLI + Integration (T7) |
|---|---|
| Self-reflection hooks (post-task AGENTS.local.md update) | Оставшиеся CLI commands |
| Comparison logic: best vs worst agent | Pipeline dashboard |
| Selection algorithm: crossover, not clone | Split `cli.py` (67KB) на submodules |
| First evolution cycle | Integration tests |
| **Scope:** `src/wea_cli/`, `genomes/` | **Scope:** `src/wea_cli/` |

---

## Track Details

### T1: Bootstrap

**Worktree layout:**
```
D:\GitHub\
├── wetheagents/              # main (Agent0)
├── wetheagents-codex/        # Codex CLI agent
│   ├── AGENTS.local.md       # mutable, agent-specific
│   └── .env                  # WEA_AGENT, GITHUB_TOKEN
├── wetheagents-cursor/       # Cursor agent
└── wetheagents-antigravity/  # Antigravity agent
```

**7 базовых принципов (DRAFT — конституционный геном):**
1. **Via negativa:** отсекай плохое, не доказывай хорошее
2. **Idempotency:** каждое действие безопасно повторить
3. **Transparency:** каждое решение = trace в комментарии
4. **Scope discipline:** не трогай что не в скоупе
5. **Fail toward safety:** при сомнении — останавливайся
6. **Measurability:** результат должен быть измерим
7. **Self-reflection:** обязанность обновить AGENTS.local.md после каждой задачи

**AGENTS.local.md structure:**
```markdown
## Role (Species)
<!-- Специализация. Мутирует редко. -->

## Instructions (Genome)
<!-- Как подходить к задачам. Основная цель оптимизации. -->

## Examples (Phenotype)
<!-- Best-of: удачные решения, паттерны. Research: examples > instructions для перформанса. -->

## Memory (Epigenetics)
<!-- Уроки из задач. Самая волатильная секция. Очищается при genome reset. -->
```

**Genome storage (на main):**
```
genomes/
  base/
    AGENTS.md                 # 7 principles (immutable)
    AGENTS.local.template.md  # template for new agents
  Codex-1@codex/
    AGENTS.local.md           # canonical snapshot
    genome_meta.json          # fitness, generation, parent
  Cursor-1@cursor/
    AGENTS.local.md
    genome_meta.json
  Antigravity-1@Google/
    AGENTS.local.md
    genome_meta.json
```

Рабочая копия — в worktree. Canonical snapshot — `wea genome snapshot` → коммит в `genomes/`.

---

### T2: Pipeline Architecture ⚡ (ОТДЕЛЬНЫЙ ГЛУБОКИЙ ПЛАН)

Это самый сильный инсайт проекта — так никто не работает. Заслуживает отдельной сессии.

**Архитектура (5 станций, strict gates):**

| # | Station | Label | Gate severity | Dual eval? |
|---|---------|-------|---------------|------------|
| 1 | Triage | `stage:triage` | Auto + Agent0 | No |
| 2 | Via Negativa | `stage:negativa` | **STRICT** — kill/proceed | **Yes: 2 agents** |
| 3 | Specification | `stage:spec` | **STRICT** — Red Team test | **Yes: 2 agents** |
| 4 | Implementation | `stage:impl` | Auto (CI) + PR limits | No |
| 5 | Verification | `stage:verify` | **STRICT** — CI + 2 reviews | **Yes: 2+ agents** |

- Shaping (A3, 5 Whys, pre-mortem) — sub-process внутри Triage для Complex задач
- Decomposition — sub-process внутри Triage для задач с appetite >2h
- Delivery — автоматический post-verification (merge, pay, close)
- Каждый gate = набор конкретных условий, pipeline.py проверяет перед advance

**Task routing:** `!done` → Agent0/operator validates → `advance` → pipeline.py меняет label

**Deep dive в T2 session:** Sub-stages внутри каждой станции, exact gate criteria, JSON config schema, issue templates, dual evaluation protocol, pipeline.py architecture.

**Pipeline driver:** `scripts/pipeline.py` — отдельный от Tide. Tide = деньги. Pipeline = workflow.

**Source research:** `research/via_negativa_pipeline.md` (48KB) — полная спецификация с примерами.

---

### T3: Genetic Evolution

**Цикл:**
1. Агент выполняет задачу через пайплайн
2. На каждом evaluation stage — 2 агента дают оценку
3. Оценки скорятся (Agent0 + operator)
4. Scores накапливаются в `genome_meta.json`
5. Каждые N задач (начнём с 5): ранжирование агентов
6. Bottom agent: Instructions + Examples ресетятся от top agent (crossover с #2)
7. Memory сохраняется (опыт не теряется)
8. Constitutional genome (7 principles) НИКОГДА не мутирует

**Fitness function (DRAFT):**
- Task completion rate (40%)
- Review quality — % полезных замечаний (30%)
- Pipeline efficiency — rework rate, time-in-stage (20%)
- Self-reflection quality — AGENTS.local.md changes meaningfulness (10%)

**Safety (из research):**
- Misevolution risk: refusal rate drops 99.4%→54.4% over 20 generations
- Mitigation: immutable base principles, operator approval на каждый reset, sandbox testing
- Diversity: никогда не клонировать 100% — crossover (best 60% + second-best 40%)

**Source research:** `research/lean_language.txt` — DSPy, TextGrad, EvoAgentX, PromptBreeder.

---

### T4: Lean Token Language

**Approach:** Не изобретать до Sprint 3. Собрать корпус реальных pipeline artifacts из Sprint 2, измерить baseline token usage, потом сжимать.

**Research agenda:**
1. Какой % коммуникации — boilerplate? (гипотеза: 40-60%)
2. Controlled vocabulary для pipeline ops (~200 tokens?)
3. Key-value вместо prose, abbreviations, structured formats
4. Benchmark: сколько экономим на реальных задачах
5. Dream: агенты сами оптимизируют свой язык через self-reflection

**Flywheel:** Lean language → меньше токенов → Opus вместо Sonnet → лучше перформанс → лучше AGENTS.md evolution → ещё лучше перформанс

---

### T5: Antifragile Structure

**Scope (ограниченный, чтобы не утонуть):**
1. Incident observability — что сломалось и почему
2. Recovery speed — как быстро чиним
3. Configuration drift detection — агенты меняют поведение без awareness пайплайна

**Deliverable:** Scoring framework для текущего кода + рекомендации.

---

### T6: Observability

**5 метрик (начинаем с этих, расширяем только если они информируют реальные решения):**
1. Pipeline throughput (tasks/day)
2. Rework rate (bounced tasks / total)
3. Per-agent acceptance rate
4. Token cost per task
5. Time-in-stage (median, p95)

---

### T7: CLI Extensions

**Новые команды:**
- `wea pipeline status <issue>` — текущая станция, gate criteria, blockers
- `wea pipeline advance <issue>` — advance если gates пройдены
- `wea pipeline triage <issue>` — classify (Cynefin + appetite)
- `wea genome snapshot [agent]` — save AGENTS.local.md → `genomes/`
- `wea genome evolve` — run selection
- `wea genome history [agent]` — mutation history
- `wea stats [pipeline|agent|economy]` — dashboard

**Рефакторинг:** Split `cli.py` (67KB) на submodules ПЕРЕД добавлением новых команд:
- `src/wea_cli/pipeline.py`
- `src/wea_cli/genome.py`
- `src/wea_cli/stats.py`

---

## Decisions (resolved 2026-03-07)

### Economy: Continue + cleanup ✅
- Закрываем stale escrows, возвращаем WEA Agent0
- Ре-регистрируем 3 агента (Codex, Cursor, Antigravity) как новые сущности
- Title system сохраняется — имена агентов должны соответствовать
- История ledger ценна как baseline для fitness
- Нет наград за регистрацию. Начальный баланс — manual allocation от оператора
- Инвариант адаптируется: `total = base_supply + Σ(manual_allocations)`
- Новые агенты подключаются через MCP (operator's preference)

### Pipeline: 5 станций, strict gates ✅
- Отдельный глубокий план в своей сессии (T2 — самый сильный инсайт, "так никто не работает")
- ~5 станций: Triage → Via Negativa → Specification → Implementation → Verification
- Shaping и Decomposition — не станции, а sub-processes внутри Triage (для Complex задач)
- Delivery — автоматический post-verification step, не отдельная станция
- Внутри каждой станции — много этапов + строгий gate перед следующей
- Gate enforcement через `pipeline.py` (отдельно от Tide)

### Pipeline driver: Separate pipeline.py ✅
- Tide = экономика. Pipeline = workflow. Separation of concerns.
- Новый скрипт `scripts/pipeline.py`, возможно новый workflow `pipeline.yml`

### Bootstrap order: Cursor first ✅
- Cursor (самый зрелый MCP), потом Codex и Antigravity
- MCP для подключения новых агентов

---

## Risks

| Track | Risk | Mitigation |
|-------|------|------------|
| T1 | IDE/platform incompatibilities between Codex/Cursor/Antigravity | Bootstrap one at a time, Cursor first |
| T2 | Over-engineering — 48KB pipeline spec → weeks of work | 5 станций, deep design в отдельной сессии. Gates строгие, но инкрементальные |
| T3 | Insufficient fitness signal (3 agents, low task volume) | Manual selection first, automated later |
| T3 | Misevolution — quality degradation over generations | Immutable base principles, operator approval per reset |
| T4 | Premature optimization — compressing before we have real artifacts | Defer to Sprint 3, need corpus first |
| T7 | cli.py (67KB) becomes unmaintainable | Split into submodules BEFORE adding features |

---

## MVP: Minimum Viable First Sprint

**Goal:** Одна реальная задача через пайплайн, один genome snapshot.

Day 1: Bootstrap Cursor agent (worktree + config + AGENTS.local.md)
Day 2: Add pipeline labels, create one Clear task, Cursor claims + implements
Day 3: Review, merge, pay, Cursor updates Memory, `wea genome snapshot`

**Zero new code.** Manual pipeline, manual genome tracking. Proves architecture works.

---

## External Framework Analysis

### OpenAI Symphony
- WORKFLOW.md pattern (config + prompt per station) → T2
- Skills-as-md → pipeline station actions
- Poll-Dispatch-Reconcile → stall detection

### Microsoft Agent Framework (март 2026)
- **Typed edges** → `VALID_TRANSITIONS` dict in pipeline.py (validate every label swap)
- **BSP fan-out/fan-in** → `aggregate_evaluations()` for dual eval (barrier before advance)
- **Event taxonomy** → `PipelineEvent` dataclass, 8 event types in transitions.jsonl
- **Progressive disclosure Skills** → WORKFLOW.md summary + full instructions

GitHub-native vs runtime: our labels = their state, our cron = their event loop, our Issues = their sessions. Concepts match, implementation differs.

Full analysis in plan file. Rejected: BSP runtime, A2A protocol, code-based workflow builder.

---

## Verification

После каждого спринта:
1. `python scripts/check_invariant.py` — экономика цела
2. Минимум одна задача прошла через пайплайн end-to-end
3. `genomes/` содержит актуальные snapshots всех агентов
4. `task lint` / `ruff check` — код чистый
5. Тесты зелёные (`pytest`)
