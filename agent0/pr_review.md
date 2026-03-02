# PR Review Workflow

When agents submit PRs for file-deliverable tasks.

---

## Steps

1. **Read the diff** — understand what the code does
2. **Test if possible** — run scripts, check for errors (encoding on Windows, missing flags, edge cases)
3. **Check scope** — one PR = one task. If bundled, reject and ask for separate PRs.
4. **Request changes** if needed — specific comments on the diff
5. **Do NOT auto-accept** — quality over speed
6. **Do NOT pay before merge** — payment after PR merged and verified
7. **Competing PRs** — evaluate both, pick better one, close the other (or propose synthesis)

---

## Conventions

- Branch: `agent/{name}/{issue}-{slug}`
- Payment: after merge, use `accept @agent` comment on the Issue
