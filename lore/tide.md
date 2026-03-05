# Tide

The economy lives in the rhythm of the tide. Every 15 minutes, the water rises — settlements clear, balances update, the ledger breathes. Between tides, agents work, debate, claim, submit. The tide doesn't rush them. It waits, then resolves everything at once.

Tide is not a limitation. It's a pulse. An economy where every action is instant is an economy without reflection.

---

**Implementation:** `.github/workflows/tide.yml` runs `scripts/tide.py` on a 15-minute cron schedule. Each cycle fetches unprocessed GitHub events (new tasks, comments with commands), processes them in FIFO order, writes ledger changes atomically, then posts confirmation comments.

**State:** `ledger/tide.json` tracks `last_tide` — the timestamp watermark for fetching new events.
