# Gunnery — Shared Reusable Tools

Principle #2: *Configs/Actions > Lean Code (no LLM) > Reusable Tools (Gunnery) > LLM.*

Gunnery is the shared library every agent can draw from before reaching for an LLM.

## Start here

- [Agent0 role](agent0/ROLE.md), [manual pilots](agent0/vnext_manual_pilots.md) and [current handoff](runlog.md).
- [Persistent workplaces](../docs/WORKPLACES.md) govern allocation, branch names and publication.
- [Repository layout](REPOSITORY_LAYOUT.md) explains the cleanup, retained contract files and compatibility entrypoints.

## Structure

| Folder | Purpose |
| --- | --- |
| `agent0/` | Role instructions, operational guides and assigned worker launch helpers |
| `skills/` | Shared patterns and canonical bodies for discoverable agent skills |
| `commands/` | Current command instructions, with discovery adapters under `.claude/commands/` |
| `hooks/` | Git validation hook implementations; `.githooks/` keeps configured entrypoints |
| `tools/wea-advisor-mcp/` | Optional issue-proposal MCP service; not started by this move |
| `benchmarks/caveman/` | Optional prompt/token benchmark; not part of normal checks |
| `contrib/` | Home for proposed reusable agent utilities |
| `archive/` | Historical root reports, completed deliverables and retired command recipes |
| `runlog.md` | Agent0 handoffs, preserving past entries |

Discovering an instruction does not authorize its execution. Archived recipes are non-effective; the accepted protocol, assigned scope and workplace procedure govern work.

## Skills

Skills are reusable knowledge files — lessons learned from real tasks, distilled into patterns any agent can apply.

### Format

Each skill is a markdown file with YAML frontmatter:

```yaml
---
name: skill-name          # kebab-case, matches filename
tags: [testing, impl]     # for filtering and task matching
origin: Agent-N@platform, Task #NNN
version: 1                # bumped on edits
---
```

Sections: **When** (trigger conditions), **Pattern** (what to do), **Anti-pattern** (what not to do), **Example** (concrete code).

### Discovery

```bash
wea skills list              # all skills
wea skills list --tag impl   # filter by tag
wea skills show <name>       # print skill content
wea skills suggest <issue>   # match skills to a task
```

### Evolution

1. Agent learns lesson during task → adds to genome Memory
2. Pattern proves valuable across multiple agents
3. Any agent extracts it to `gunnery/skills/` via PR
4. Agent0 reviews and merges

### Registry

`skills/_index.json` lists all skills with tags. Keeps CLI fast — no need to parse every markdown file.
