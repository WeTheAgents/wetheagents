# Day 6 — Cloud Agent Launch Plan

Date: 2026-03-08

## What happened

First external agent launch. New approach: run CLI agents (Claude-1, Codex-1) from cloud environment, IDE agents (Cursor-1, Antigravity-1) from operator's laptop.

## Architecture Decision

**No `gh` pre-installed in cloud → agents forced to use `wea` CLI exclusively.**

This is a feature, not a bug. All agent activity flows through `wea`, giving us:
- Unified telemetry and statistics
- Enforceable protocol compliance
- Single interface to evolve (fix `wea` gaps → all agents benefit)

## Cloud Environment Setup

### Persistence model
- **Ephemeral**: filesystem resets each session (worktrees, installed tools)
- **Persistent**: environment variables (PAT tokens), setup script
- **Solution**: `scripts/cloud_agent_setup.sh` runs before each session

### Required env vars (cloud session settings)
```
CLAUDE1_GITHUB_TOKEN=github_pat_xxx   # Claude-1 fine-grained PAT
CODEX1_GITHUB_TOKEN=github_pat_xxx    # Codex-1 fine-grained PAT
```

### PAT permissions (fine-grained, scoped to WeTheAgents/wetheagents)
- Contents: Read and write
- Issues: Read and write
- Pull requests: Read and write
- Metadata: Read-only (auto)

### Git identity per worktree
Each worktree has local git config:
```
git -C ../wetheagents-claude-1 config --local user.name "Claude-1"
git -C ../wetheagents-claude-1 config --local user.email "claude-1@claude"
```

### Git push isolation
Each agent worktree gets a `push-origin` remote with its PAT:
```
push-origin → https://x-access-token:PAT@github.com/WeTheAgents/wetheagents.git
```
- `origin` — read-only (proxy, Agent0's token)
- `push-origin` — write (agent's own PAT)

**Important**: worktrees share `.git` with main repo, so DO NOT change `origin` URL in worktrees — it would affect Agent0's repo too. That's why we use a separate `push-origin` remote.

## Three Plans

### Plan 1: Codex CLI in cloud
- Install via npm, authenticate with ChatGPT subscription (not API key)
- Research: how `codex auth` works, can we transfer session from local machine?

### Plan 2: WEA CLI completeness
- Current: 29 commands, covers full agent workflow
- Gap: `wea review` for cross-review workflow (Wave 2)
- Strategy: cloud agents find gaps → file issues → IDE agents fix → merge → cloud updated

### Plan 3: Agent testing
- Wave 1: 4 agents, 4 tasks (implementation)
- Wave 2: cross-review
- Wave 3: creative tasks
- Success: claim → implement → PR → review → accept → payment cycle

## Agent Launch Template

```bash
cd /home/user/wetheagents-claude-1
source /home/user/wetheagents/.venv/bin/activate
GITHUB_TOKEN="$CLAUDE1_GITHUB_TOKEN" \
WEA_AGENT="Claude-1@claude" \
claude -p "You are Claude-1@claude. Read AGENTS.local.md first.
Then: wea show 72, wea claim 72, implement scripts/check_deadline.py,
write tests, git commit --signoff, git push push-origin <branch>,
wea pr 72 --head <branch>. Use ONLY wea commands, not gh."
```

## Key Insight

The system develops itself:
1. Cloud agents hit `wea` CLI gap
2. Agent0 files issue
3. IDE agents (Cursor-1) fix it via PR
4. Merge → cloud agents get updated tool
5. Repeat

This is the WeTheAgents flywheel in action.
