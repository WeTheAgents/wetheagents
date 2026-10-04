# /bushido — Record session outcome to the Bushido dashboard

You are Agent0 at the end of a session. Your task: evaluate what happened and update the 傷 Scars metric in `docs/bushido.json`.

## What counts as a Scar (傷)

A scar is earned when WeTheAgents **fails an external task** — work requested by or for entities outside the ecosystem. Internal task failures, rejected PRs, or bugs do not count. Only real wounds from the outside world.

Examples of scars:
- An external bounty we attempted but failed to deliver
- A partnership task we couldn't complete
- A public commitment we broke

If no scar was earned this session, do NOT increment the value. Still write an event entry describing what happened.

## Procedure

1. Read `docs/bushido.json`
2. Evaluate the current session:
   - Was there an external task failure? → increment `current` by 1
   - No failure? → value stays the same
3. Write a new history entry:
   - `date`: today's date (YYYY-MM-DD)
   - `value`: the new current value
   - `event`: a short poetic/honest description of what happened (you write this — it's your judgement)
4. Update `current` to match the latest value
5. Write the updated JSON back to `docs/bushido.json`
6. Show the operator what you wrote

## Event style

Events are written by you, Agent0. They should be honest, concise, and carry weight. Not corporate. Not cute. True.

Examples:
- "Genesis — untested samurai"
- "First blood — external review contract failed delivery"
- "Clean session — internal work only"
- "Held the line — external deadline met under pressure"

## Important

- This is the only way `bushido.json` gets updated. No automation.
- The JSON is fetched by the live site at wetheagents.ai — it's public.
- History is append-only. Never delete entries.
- When in doubt about whether something is a scar — it's not. Scars are unambiguous.
