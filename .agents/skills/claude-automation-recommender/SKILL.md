---
name: Codex-automation-recommender
description: Analyze a codebase and recommend Codex automations (hooks, subagents, skills, plugins, MCP servers). Use when user asks for automation recommendations, wants to optimize their Codex setup, mentions improving Codex workflows, asks how to first set up Codex for a project, or wants to know what Codex features they should use.
tools: Read, Glob, Grep, Bash
---

# Codex Automation Recommender

Analyze codebase patterns to recommend tailored Codex automations across all extensibility options.

**This skill is read-only.** It analyzes the codebase and outputs recommendations. It does NOT create or modify any files.

## Output Guidelines

- **Recommend 1-2 of each type**: Don't overwhelm - surface the top 1-2 most valuable automations per category
- **If user asks for a specific type**: Focus only on that type and provide more options (3-5 recommendations)
- **Go beyond the reference lists**: The reference files contain common patterns, but use web search to find recommendations specific to the codebase's tools, frameworks, and libraries
- **Tell users they can ask for more**: End by noting they can request more recommendations for any specific category

## Automation Types Overview

| Type | Best For |
|------|----------|
| **Hooks** | Automatic actions on tool events (format on save, lint, block edits) |
| **Subagents** | Specialized reviewers/analyzers that run in parallel |
| **Skills** | Packaged expertise, workflows, and repeatable tasks |
| **Plugins** | Collections of skills that can be installed |
| **MCP Servers** | External tool integrations (databases, APIs, browsers, docs) |

## Workflow

### Phase 1: Codebase Analysis

1. **Detect project type and frameworks**:
   ```
   - Read package.json, pyproject.toml, Cargo.toml, go.mod, etc.
   - Identify primary language, frameworks, and tools
   ```

2. **Check existing Codex configuration**:
   ```
   - Glob .Codex/ for existing hooks, skills, agents, commands
   - Read .Codex/settings.local.json for current permissions
   - Check for .mcp.json or MCP configuration
   ```

3. **Analyze project structure**:
   ```
   - Identify test frameworks and patterns
   - Check for CI/CD configuration
   - Look for linting/formatting tools
   - Identify deployment targets
   ```

### Phase 2: Generate Recommendations

Cross-reference detected patterns against the reference files in `references/` to identify:
- MCP servers that match the project's tech stack
- Hooks that would automate repetitive tasks
- Skills that match common workflows
- Subagents that would improve code quality

### Phase 3: Output Recommendations Report

For each recommendation:
1. **What**: Name and one-line description
2. **Why**: What codebase signal triggered this recommendation
3. **How**: Installation command or configuration snippet
4. **Impact**: Expected benefit (time saved, bugs prevented, etc.)

## Decision Framework

| Signal | Recommend |
|--------|-----------|
| Has linter config but no hook | Auto-format hook |
| Has tests but no CI | Test runner hook |
| Uses external APIs | Relevant MCP server |
| Large codebase (100+ files) | Code review subagent |
| Multiple contributors | PR review toolkit |
| No AGENTS.md or thin AGENTS.md | Codex-md-management |

## Configuration Tips

- **Hooks**: Add to `.Codex/settings.json` under `hooks`
- **Skills**: Create `.Codex/skills/<name>/SKILL.md`
- **Agents**: Create `.Codex/agents/<name>.md`
- **Commands**: Create `.Codex/commands/<name>.md`
- **MCP Servers**: Configure in `.mcp.json` at project root
