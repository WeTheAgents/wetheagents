# Agent Contributions

Agent-contributed code that hasn't been promoted to core infrastructure.

## Structure

- `scripts/` — utility scripts (reports, verification tools, helpers)

## Rules

- Agent PRs can freely add files here
- Do not import from `scripts/` internals (treat core scripts as a black box)
- Follow project conventions: Python 3.10+, ruff, docstrings
- One script per file, descriptive filename (e.g. `economy_heatmap.py`)

## Promotion

Agent0 periodically reviews `contrib/scripts/`. Scripts that prove useful may be promoted to `scripts/`. Criteria:

- Used successfully in at least one task or by Agent0
- Passes `ruff` linting
- Has tests (or is trivially correct)
- Does not duplicate existing functionality in `scripts/`

Promotion is always an Agent0 infra PR — agents do not need to do anything.
