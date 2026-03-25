---
description: "Comprehensive PR review using specialized agents"
argument-hint: "[review-aspects: comments|tests|errors|types|code|simplify|all]"
allowed-tools: ["Bash", "Glob", "Grep", "Read", "Agent"]
---

# PR Review Command

Run specialized review agents on the current changes.

## Context

- Current git status: !`git status`
- Current branch: !`git branch --show-current`

## Review Aspects

Available aspects (comma-separated or "all"):
- **comments** → comment-analyzer agent
- **tests** → pr-test-analyzer agent
- **errors** → silent-failure-hunter agent
- **types** → type-design-analyzer agent
- **code** → code-reviewer agent
- **simplify** → code-simplifier agent
- **all** → run all agents

## Your Task

1. Parse the requested review aspects from `$ARGUMENTS` (default: "all")
2. For each requested aspect, launch the corresponding agent from `.claude/agents/`
3. Each agent reviews `git diff` (unstaged) or `git diff --cached` (staged)
4. Collect results from all agents
5. Present a unified report grouped by:
   - **Critical Issues** (confidence 90-100)
   - **Important Issues** (confidence 80-89)
   - **Suggestions** (confidence < 80 but noteworthy)
   - **Positive Observations**

Each finding should include: file:line, agent source, description, confidence score.

Launch agents in parallel when possible for speed.
