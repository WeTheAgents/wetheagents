# Subagent Templates Reference

## Code Review Agents

### code-reviewer
- **Model**: opus (high accuracy needed)
- **Tools**: Read, Glob, Grep, Bash(git diff)
- **Use**: General code quality review with confidence scoring

### security-reviewer
- **Model**: opus
- **Tools**: Read, Glob, Grep
- **Use**: Security-focused review (injection, XSS, auth, secrets)

### test-writer
- **Model**: sonnet (speed over depth)
- **Tools**: Read, Glob, Grep, Write, Bash(pytest)
- **Use**: Generate tests for uncovered code paths

## Specialized Agents

### api-documenter
- **Model**: sonnet
- **Tools**: Read, Glob, Grep, Write
- **Use**: Generate/update API documentation from code

### performance-analyzer
- **Model**: opus
- **Tools**: Read, Glob, Grep, Bash
- **Use**: Profile and optimize performance bottlenecks

## Model Selection Guide

| Need | Model | Why |
|------|-------|-----|
| High accuracy, complex reasoning | opus | Best for reviews, architecture |
| Speed, iteration, simple tasks | sonnet | Good for generation, formatting |
| Bulk operations, filtering | haiku | Cheapest for triage, classification |
| Inherit from parent | inherit | Use parent session's model |

## Tool Access Guide

| Access Level | Tools | Use Case |
|-------------|-------|----------|
| Read-only | Read, Glob, Grep | Reviews, analysis |
| Writing | + Write, Edit | Code generation, refactoring |
| Full | + Bash, Agent | Complex workflows, testing |
