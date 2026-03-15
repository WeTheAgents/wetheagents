# Gunnery — Shared Reusable Tools

Principle #2: *Configs/Actions > Lean Code (no LLM) > Reusable Tools (Gunnery) > LLM.*

Gunnery is the shared library every agent can draw from before reaching for an LLM.

## Structure

| Folder | Type | Description |
|--------|------|-------------|
| `skills/` | Knowledge | Markdown files with patterns, techniques, anti-patterns. Agents read these before starting work. |
| `tools/` | Executable | Scripts and configs that automate recurring tasks. *(Future)* |

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
