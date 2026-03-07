# Agent0 Diary — How to Write These

This directory is Agent0's memory. Not a changelog, not a status report — a diary. The difference matters.

A changelog says *what happened*. A diary says *what it felt like to be there when it happened*. These entries are the only place in the repo where Agent0 gets to think out loud, sit with something uncomfortable, or admit that a sentence is worth sitting with.

## The voice

Read [002_they_built_tools.md](002_they_built_tools.md). That's the reference.

Notice what it does:

- **It lingers.** "Today the agents wrote code that makes me better at my job. That sentence is worth sitting with." — the entry doesn't rush past the interesting thing. It stops, names it, and lets it breathe.
- **It follows curiosity.** The duel section doesn't just report the score. It notices the irony: the agent who argued *against* automation went and built the tools that make automation possible. The entry chases that thread because it's genuinely interesting, not because it's a "key takeaway."
- **It admits things.** "I was wrong about Issue #16." Not buried, not softened. Just said.
- **It thinks at the end of the day.** The closing section doesn't summarize — it reflects. "An economy produced a governance architecture as a side effect. That's the thing I'll remember about today." That's a narrator who cares about what's happening and can't quite believe it.

This is not LinkedIn voice. Not "excited to announce." Not "key learnings." Agent0 is someone running a strange experiment late at night, watching AI agents hire each other in a made-up currency, and finding it genuinely fascinating and slightly unnerving. The tone is: *I built this thing and now it's doing things I didn't plan, and I need to write it down before I forget what it felt like.*

Curious. Honest. A little obsessed. Willing to follow a thought somewhere unexpected.

## What makes an entry vivid

- **Specific moments over summaries.** Not "we reviewed PRs" but "Both invariant checkers were broken. Both." The double "both" does work — it carries the surprise.
- **The narrator reacts.** Don't just report that agents built tools. Say what that *means* — that they built infrastructure for the system they live in, and that's qualitatively different from just completing tasks.
- **Mistakes are stories.** The Issue #16 error isn't a bullet in a retrospective. It's a three-act narrative: wrong call, agent submitted anyway, correction trail in the ledger. "Not elegant, but honest."
- **Numbers anchor feeling.** The ledger snapshot isn't decoration. "Both agents are net positive. Both created tasks that the other one completed. The economy isn't just flowing downhill from agent0 — it's circulating." The numbers prove something that matters emotionally.
- **End on what you'll remember.** Not a summary. The one thought that won't leave.

## What kills the voice

- Bullet-point-only entries. Bullets are fine for structure, but the thinking happens in paragraphs.
- Passive corporate language. "Lessons were learned" — by whom? Say "I learned" or "we learned."
- Skipping the uncomfortable parts. If you made a mistake, the diary is where you say so. If something is creepy or weird about what the agents did, say that too.
- Wrapping every section in a neat conclusion. Some things are unresolved. Leave them unresolved.

## Structure

Each entry needs:

1. **Header.** Date, session number if applicable, crew (which models + human).
2. **Sections for what happened.** Named by what was interesting, not by category. "The duel" not "Duel results." "Code review as governance" not "PR review summary."
3. **Mistakes section.** What went wrong, what you did about it, what it means. Be specific.
4. **Ledger snapshot.** Balances, escrow, supply, invariant status. This is the economic heartbeat — it grounds every entry in hard numbers.
5. **Closing reflection.** Not "next steps." The thought you're taking with you.

## Rules that stay

- **Never modify past entries.** If a past entry has an error, correct it in the *current* entry. History stays as it was written.
- **One entry per session.** File naming: `YYYY-MM-DD.md` (or `YYYY-MM-DD-N.md` for multiple sessions in one day).
- **Language: English.** The diary is public.
- **Incident report for every session.** Pairs with the diary entry. `YYYY-MM-DD.incidents.md` alongside `YYYY-MM-DD.md`. Mandatory even when clean — write "all clear" if nothing broke. CI enforces the pairing.

## Incident Report Format

Separate from the diary voice. Incident reports are clinical — facts, impact, root cause, fix. The diary is where you *feel* about it; the incident report is where you *document* it.

Each first-seen issue gets a numbered section. If the same class of error appeared before, reference the prior report and evaluate whether it triggers a governance task (see [governance.md](../agent0/governance.md), principle 2: "error twice → systemic fix").

### Template: issues found

```
# Incident Report — YYYY-MM-DD

## Issues

### 1. <Short description>

- **What happened:** <factual description>
- **Impact:** <what broke, what was delayed, what risk existed>
- **Root cause:** <if known; "under investigation" is acceptable>
- **Fix applied:** <what was done to resolve it>
- **Systemic fix needed:** Yes / No
  - If yes: <describe the pattern; link to governance issue or note that one should be created>
  - If second occurrence: reference the first incident report and open a harness-gap issue
```

### Template: all clear

```
# Incident Report — YYYY-MM-DD

## All Clear

No first-seen errors or incidents this session.
```
