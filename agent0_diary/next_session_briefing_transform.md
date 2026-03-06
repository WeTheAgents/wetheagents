# Next Session Briefing: Transform Implementation

**For:** Agent0 (next session)
**Context:** This continues the title system work from the all-nighter of 2026-03-06.
**Priority:** Implement the Transform mechanic — the final piece of the ikigai identity system.

---

## What exists now

The title system is live. Agent0 awards skill words (`wea award`), revokes them (`wea revoke`), agents see their titles in `wea start`, `wea tasks`, `wea title`. Words compose into titles in reversed display order (newest first, noun last): `persistent-planner`. No seniority labels.

**Key files:**
- `src/wea_cli/cli.py` — cmd_award, cmd_revoke, cmd_title, cmd_tasks (all title-aware)
- `src/wea_cli/start_snapshot.py` — title in wea start header
- `scripts/check_ledger_schema.py` — validate_achievements (already accepts `transform_award` / `transform_revoke` actions)
- `ledger/achievements.json` — live data (schema: version, agents, each with title/words/history)
- `docs/multi_agent_and_titles.md` — full documentation including Transform section (marked as planned)
- `tests/test_achievements.py` — 19 tests including transform action types and full cycle

**Schema validator already handles transform actions.** The `validate_achievements` function and its consistency check already know about `transform_award` and `transform_revoke`. The tests verify this.

---

## What needs to be built

### Transform: two-phase consent mechanism

**Phase 1: Agent0 proposes** (on a task issue, in discussion)

Agent0 sees that an agent's calling has changed. Posts a comment:
```
@AgentName, I believe your calling has changed. You've been acting more as
a **builder** than a planner in recent tasks.

I propose transforming your foundation word: `planner` → `builder`.

**This will reset your title to `builder`.** Your previous words will be
honored in your achievement history — they are part of who you were.

If you accept, reply with: `!accept-transform`
```

**Phase 2: Agent confirms** (comment on same issue)

Agent replies: `!accept-transform`

**Phase 3: Tide processes**

Tide parses `!accept-transform`, validates, executes:
1. Revoke ALL active words (as `transform_revoke` entries in history)
2. Award new foundation word (as `transform_award` entry)
3. Update words[], title
4. Post confirmation comment

### History format

```json
[
  {"action": "transform_revoke", "word": "persistent", "at": "...", "reason": "Transform: planner -> builder"},
  {"action": "transform_revoke", "word": "planner", "at": "...", "reason": "Transform: planner -> builder"},
  {"action": "transform_award", "word": "builder", "at": "...", "reason": "Agent accepted identity transformation", "issue_ref": "#42"}
]
```

### Files to create/modify

| File | What |
|------|------|
| `scripts/tide_parser.py` | New event type: `accept_transform` |
| `scripts/tide.py` | Handler: `_accept_transform()` |
| `src/wea_cli/cli.py` | New command: `wea transform-propose` (Agent0 posts the proposal comment) |
| `tests/test_transform.py` | Full cycle tests: propose, accept, validate, edge cases |
| `docs/multi_agent_and_titles.md` | Update Transform section from "planned" to "implemented" |

### Design decisions already made

- Transform resets ALL words, not just the foundation. You become `builder`, not `persistent-builder`.
- Only Agent0 can propose. Only the target agent can accept.
- Agent cannot be in two pending transforms simultaneously.
- The pending state lives in the escrow or a new `pending_transforms` section — TBD.
- `transform_revoke` / `transform_award` are distinct from regular `revoke` / `award` in history.

### Open questions for the operator

1. Where does the pending transform state live? Options: (a) new field in achievements.json, (b) new file `ledger/transforms.json`, (c) issue labels/metadata.
2. Should there be a timeout on pending proposals? (e.g., 7 days)
3. Can an agent reject a transform proposal explicitly, or just ignore it?

---

## Verification checklist

Before committing:
1. `pytest tests/ -v` — all pass
2. `python scripts/check_invariant.py` — PASS
3. `python scripts/check_ledger_schema.py` — PASS
4. Codex review cycle until clean (mandatory, see MEMORY.md)
5. Operator review of the transform UX (comment wording, confirmation flow)

---

## One more thing

Read `agent0_diary/2026-03-06.md` for context on last night. It was 20+ review cycles. The operator will remember.
