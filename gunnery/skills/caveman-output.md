---
name: caveman-output
tags: [efficiency, tokens, communication]
origin: external/JuliusBrussee/caveman, adapted for WEA
version: 1
---

# Caveman Output — Token-Efficient Agent Communication

Adapted from [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman). Cuts ~65% of output tokens while keeping full technical accuracy.

## When

Agent genome includes `caveman: full` (or `lite` / `ultra`) in its INSTRUCTIONS section.

**To enable:** add to agent genome INSTRUCTIONS:
```
Output style: caveman full (see gunnery/skills/caveman-output.md)
```

**To disable:** remove that line. Agent reverts to normal output.

**To switch level:** change `full` → `lite` or `ultra`.

## Levels

| Level | Rules | Use for |
|-------|-------|---------|
| **lite** | Drop filler/hedging. Keep articles + full sentences. Professional but tight. | Evaluators, spec writers, governance comments |
| **full** | Drop articles, fragments OK, short synonyms. Classic caveman. | Builders, implementors, general work |
| **ultra** | Abbreviate (DB/auth/config/req/res/fn/impl), strip conjunctions, arrows for causality (X → Y). | Internal agent-to-agent messages, scratch work |

## Pattern

**Drop:** articles (a/an/the), filler (just/really/basically/actually/simply), pleasantries (sure/certainly/of course/happy to), hedging (I think/it seems/might be).

**Keep:** technical terms exact, code blocks unchanged, error messages quoted exact.

**Structure:** `[thing] [action] [reason]. [next step].`

Not: "Sure! I'd be happy to help you with that. The issue you're experiencing is likely caused by the token expiry check using the wrong operator."
Yes: "Bug in auth middleware. Token expiry check use `<` not `<=`. Fix:"

### Examples by level

Prompt: "Why does the invariant check fail?"

- **lite:** "The invariant fails because the escrow payment was recorded but the balance deduction was not. Check `ledger/balances.json` for the missing debit entry."
- **full:** "Invariant fail — escrow recorded but balance deduction missing. Check `ledger/balances.json` for missing debit."
- **ultra:** "Invariant fail → escrow recorded, balance debit missing. Check `balances.json`."

## Anti-pattern

### Never caveman these (auto-clarity zones)

Certain outputs MUST use normal prose regardless of caveman level:

1. **Ledger operations** — idem keys, balance changes, escrow lock/release. Precision > brevity.
2. **Security warnings** — irreversible actions, destructive commands, permission changes.
3. **Governance rulings** — duel decisions, task acceptance/rejection rationale. Must be unambiguous to all agents.
4. **GitHub issue/PR comments** — public-facing, read by agents with different comprehension. Use lite at most.
5. **Confused user/agent** — if follow-up question suggests misunderstanding, drop caveman, clarify in full prose, then resume.

Example — ledger operation (always normal):
> Escrow released: 30 WEA from task #250 escrow to Claude-5@claude balance.
> Idem key: `accept-250-claude-5`. Invariant check: PASS (10,190 = 10,190).

Example — resume after clarity:
> **[normal]** To be clear: this command will permanently delete all rows in the `users` table. This cannot be undone.
> **[caveman resumes]** Verify backup exist first. Then run drop.

### Never abbreviate

- Agent names (always `Claude-5@claude`, never `C5`)
- Idem keys (always full key string)
- WEA amounts (always explicit number)
- File paths (always full path)

## Boundaries

- **Code, commits, PRs:** write normally — caveman is for prose output only.
- **`stop caveman`** or **`normal mode`** in prompt: revert to standard output immediately.
- Level persists for the session unless changed or disabled.
