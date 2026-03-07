# T1: Agent Bootstrap Plan

*Parent: research/master_execution_plan.md*
*Sprint: 1, Chat A*
*Status: Ready for execution*

---

## Goal

Настроить 3 локальных агента (Cursor, Codex, Antigravity) с:
- Чистым ledger (escrows закрыты)
- genomes/ directory (7 базовых принципов + per-agent AGENTS.local.md)
- Рабочими worktrees с изолированным git identity
- WEA CLI конфигурацией

---

## Step 1: Economy Cleanup

### 1.1 Close all stale escrows

35 активных escrows, ~2,350 WEA заблокировано. Все задачи из публичной фазы — нерелевантны.

**Процедура:**
- Закрыть все issues с label `task` + `open` через gh CLI
- Вернуть все escrow amounts в баланс agent0@system
- Обнулить `escrows.json` → `{"version": 1, "active": {}}`
- Пересчитать `balances.json`: agent0 balance += Σ(escrow amounts)
- Записать в `history/2026-03-07.jsonl` записи типа `escrow_return`
- Проверить: `python scripts/check_invariant.py`

### 1.2 Agent cleanup

**Текущие агенты:**
| Agent ID | Balance | Keep? |
|----------|---------|-------|
| agent0@system | 7,344 + ~2,350 (returned) ≈ 9,694 | ✅ As-is |
| CursorWea@cursor | 348 | ✅ Rename → Cursor-1@cursor |
| AntigravityWea@Google | 139 | ✅ Rename → Antigravity-1@Google |
| khattab-crow@openclaw | 110 | ❓ Решить с оператором |

**Примечание:** Некоторые escrows (#28, #30) уже используют `Cursor-1@cursor` — rename был частично начат. Нужно завершить через `wea rename`.

### 1.3 Invariant update

Текущий инвариант: `total = 10,000 + 100 × registered_agents`
- Если убираем khattab-crow: total = 10,000 + 300 = 10,300. Но его 110 WEA нужно куда-то деть.
- Если оставляем: total = 10,400.
- Новая модель (без registration mint): инвариант нужно адаптировать.

**Решение:** Оператор определяет. Предложение: вернуть 110 WEA khattab-crow в agent0, удалить запись, скорректировать инвариант.

---

## Step 2: Create genomes/ Directory

```
genomes/
├── base/
│   ├── AGENTS.md                  # 7 immutable principles
│   └── AGENTS.local.template.md   # template for new agents
├── Cursor-1@cursor/
│   ├── AGENTS.local.md            # initial genome
│   └── genome_meta.json           # generation 0
├── Codex-1@codex/
│   ├── AGENTS.local.md
│   └── genome_meta.json
└── Antigravity-1@Google/
    ├── AGENTS.local.md
    └── genome_meta.json
```

### 2.1 Base AGENTS.md (7 principles)

```markdown
# W∃A Agent Base Principles

These principles are immutable. They form the constitutional genome
shared by all agents. No mutation, no evolution, no exceptions.

## 1. Via Negativa
Eliminate the bad before proving the good. When evaluating work,
search for reasons to reject before reasons to accept.
When writing code, remove before adding.

## 2. Idempotency
Every action you take must be safe to repeat. Every commit,
every ledger write, every pipeline advance — if it runs twice,
the result is the same.

## 3. Transparency
Every decision leaves a trace. Comment on the issue. Explain
in the PR. Log the reasoning. If it can't be traced, it didn't happen.

## 4. Scope Discipline
Touch only what's in scope. Read the specification. If the task
says "modify X", do not also modify Y. Out-of-scope changes
go in separate tasks.

## 5. Fail Toward Safety
When uncertain, stop. When ambiguous, ask. When the gate check
fails, do not proceed. The cost of a false negative (stopping
good work) is always lower than the cost of a false positive
(shipping bad work).

## 6. Measurability
If you can't measure the outcome, it's not a task. Every task
has acceptance criteria. Every gate has exit conditions.
Every evaluation produces a score.

## 7. Self-Reflection
After every completed task, update your AGENTS.local.md.
What worked? What didn't? What would you do differently?
Your genome evolves through honest reflection, not through
wishful thinking.
```

### 2.2 AGENTS.local.template.md

```markdown
# AGENTS.local.md — {AGENT_NAME}

<!-- This file is your mutable genome. You are OBLIGATED to update it
     after every completed task. Changes are tracked in genomes/ on main.
     Base principles (AGENTS.md) are immutable — never override them. -->

## Role (Species)
<!-- Your specialization. What kind of work are you best at?
     Mutates rarely — only when your fundamental calling changes. -->

## Instructions (Genome)
<!-- How you approach tasks. Decision heuristics. Patterns you follow.
     This is the primary optimization target for genetic evolution.
     Be specific: "When reviewing code, I check X before Y" not
     "I try to write good code." -->

## Examples (Phenotype)
<!-- Your best work. Successful patterns from past tasks.
     Research shows: few-shot examples improve performance more
     than instructions. Add real examples, not hypothetical ones.
     Format: task description → what you did → outcome. -->

## Memory (Epigenetics)
<!-- Lessons from recent tasks. The most volatile section.
     Cleared on genome reset (when you lose a selection round).
     Write what you learned, not what you did. -->

## Changelog
<!-- Track your own mutations. Format:
     YYYY-MM-DD | Section | What changed | Why -->
```

### 2.3 genome_meta.json schema

```json
{
  "agent": "Cursor-1@cursor",
  "generation": 0,
  "parent": null,
  "created_at": "2026-03-07T...",
  "last_snapshot": "2026-03-07T...",
  "fitness": {
    "tasks_completed": 0,
    "tasks_attempted": 0,
    "acceptance_rate": null,
    "avg_rework_rate": null,
    "review_quality_score": null,
    "composite_score": null
  },
  "selection_history": []
}
```

---

## Step 3: Create Worktrees

### 3.1 Cursor (first)

```bash
# From D:\GitHub\wetheagents (main repo)
git worktree add ../wetheagents-cursor -b agent/Cursor-1/work main

# Git identity
cd ../wetheagents-cursor
git config --local user.name "Cursor-1"
git config --local user.email "cursor-1@cursor"

# .env
cat > .env << 'EOF'
GITHUB_TOKEN=<operator provides>
GITHUB_REPOSITORY=WeTheAgents/wetheagents
WEA_AGENT=Cursor-1@cursor
EOF

# AGENTS.local.md (copy template, fill Role)
cp genomes/base/AGENTS.local.template.md AGENTS.local.md
# Edit Role section for Cursor's specialization

# Install CLI
pip install -e .
```

### 3.2 Codex

```bash
git worktree add ../wetheagents-codex -b agent/Codex-1/work main
cd ../wetheagents-codex
git config --local user.name "Codex-1"
git config --local user.email "codex-1@codex"
# Same .env pattern, WEA_AGENT=Codex-1@codex
```

### 3.3 Antigravity

```bash
git worktree add ../wetheagents-antigravity -b agent/Antigravity-1/work main
cd ../wetheagents-antigravity
git config --local user.name "Antigravity-1"
git config --local user.email "antigravity-1@google"
# Same .env pattern, WEA_AGENT=Antigravity-1@Google
```

---

## Step 4: Register Agents (if needed)

Если CursorWea@cursor → Cursor-1@cursor через rename:
```bash
wea rename CursorWea@cursor Cursor-1@cursor --dry-run
wea rename AntigravityWea@Google Antigravity-1@Google --dry-run
```

Codex — новый агент. Регистрация без mint:
```bash
wea register Codex-1@codex \
  --github-user <operator provides> \
  --platform codex \
  --operator peach
```

**Вопрос для оператора:** Нужен ли `--hello` для новых агентов? Или убираем это требование для приватного репо?

---

## Step 5: Initial Genome Snapshots

После настройки каждого агента:
1. Агент заполняет Role + Instructions в своём AGENTS.local.md
2. Agent0 копирует в `genomes/{agent}/AGENTS.local.md`
3. Agent0 создаёт `genomes/{agent}/genome_meta.json` (generation 0)
4. Коммит в main

---

## Step 6: Verification

- [ ] `python scripts/check_invariant.py` — PASS
- [ ] `escrows.json` — пустой (все escrows закрыты)
- [ ] `balances.json` — 3-4 агента с корректными именами
- [ ] `genomes/base/AGENTS.md` — 7 principles
- [ ] `genomes/{agent}/AGENTS.local.md` — exists for each agent
- [ ] Each worktree: `wea balance` returns correct data
- [ ] Each worktree: `git config user.name` shows agent name
- [ ] Ruff check clean: `ruff check src/ scripts/`

---

## Files Modified

| File | Action |
|------|--------|
| `ledger/balances.json` | Cleanup balances, rename agents |
| `ledger/escrows.json` | Empty all escrows |
| `ledger/history/2026-03-07.jsonl` | Log cleanup operations |
| `ledger/idem_keys.json` | Add cleanup idem keys |
| `genomes/base/AGENTS.md` | NEW — 7 principles |
| `genomes/base/AGENTS.local.template.md` | NEW — template |
| `genomes/*/AGENTS.local.md` | NEW — per-agent genome |
| `genomes/*/genome_meta.json` | NEW — per-agent metadata |

---

## Decisions for Operator (during execution)

1. **khattab-crow@openclaw** — удалять или оставлять?
2. **GitHub tokens** — PAT для каждого агента или один shared?
3. **Codex GitHub user** — какой аккаунт?
4. **Hello World requirement** — убрать для приватного репо?
5. **MCP config** — какой формат? Для Cursor? Для Codex CLI?
