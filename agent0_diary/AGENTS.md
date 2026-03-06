# Agent0 Diary — Guidelines

This directory contains Agent0's operational diary. Each entry captures one working session — a continuous block of collaboration between Agent0 and the operator. The diary is a record of joint work, not a solo log.

## Rules

1. **Never modify past entries.** They are the historical record. If a past entry contains an error, note the correction in the *current* entry.
2. **One entry per session.** File naming: `YYYY-MM-DD.md` (or `YYYY-MM-DD-N.md` if multiple sessions in one day). A session = one continuous conversation between Agent0 and the operator. The tempo may change — some days have three sessions, some weeks have none.
3. **Write honestly.** Mistakes, misjudgments, and open questions are as valuable as successes. The diary is for learning, not performance.
4. **Include the ledger snapshot.** Every entry ends with a balance/escrow summary. This creates a traceable economic timeline independent of the ledger itself.
5. **Language: English.** The diary is part of the public repo.
6. **Incident report for every session.** Alongside every diary entry, create a corresponding incident report. This enforces the antifragility loop: notice once and fix, notice twice and systematize.
   - **Naming:** `YYYY-MM-DD.incidents.md` pairs with `YYYY-MM-DD.md`. For multi-session days: `YYYY-MM-DD-N.incidents.md` pairs with `YYYY-MM-DD-N.md`.
   - **Mandatory even when clean.** If no errors occurred, the incident report must still exist with an "all clear" note. CI enforcement is simple: diary entry exists → incident report must exist.
   - **CI enforced.** A guard workflow checks that every diary entry in a PR has a corresponding `.incidents.md` file. PRs without the pair will fail.

## Incident Report Format

Each first-seen issue gets its own numbered section. If the same class of error appeared before, reference the prior incident report and evaluate whether this is the second occurrence that triggers a governance task (see [governance.md](../agent0/governance.md), principle 2: "error twice → systemic fix", and the Harness Gap Process).

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
