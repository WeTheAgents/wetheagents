# Agent Switching Protocol

How to run multiple agents from one machine. Supports both sequential
(one IDE chat, switching identities) and parallel (multiple terminals).

---

## Agent Map

| Agent | Worktree | WEA_AGENT | Platform |
|-------|----------|-----------|----------|
| Cursor-1 | `D:\GitHub\wetheagents-cursor-1` | `Cursor-1@cursor` | Cursor IDE |
| Codex-2 | `D:\GitHub\wetheagents-codex-2` | `Codex-2@codex` | Codex CLI |
| Claude-1 | `D:\GitHub\wetheagents-claude-1` | `Claude-1@claude` | Claude Code CLI |
| gemini-4 | `D:\GitHub\wetheagents-gemini-4` | `gemini-4@google` | Gemini CLI |
| Claude-17 | `D:\GitHub\wetheagents-claude-17` | `Claude-17@claude` | Claude Code CLI |

---

## Sequential Switching (one IDE, multiple agents)

The operator tells the AI assistant which agent to work as.

### Protocol

1. Operator says: "Switch to Cursor-1" or "Do task X as Codex-2"
2. AI changes working directory to the agent's worktree
3. AI reads `AGENTS.local.md` in that worktree (the agent's genome)
4. AI loads `.env` or sets `WEA_AGENT` environment variable
5. AI announces: "Now working as Cursor-1@cursor"
6. All git operations use that worktree's configured identity
7. On switch: repeat from step 2 with new agent

### Identity Rules

- **Never mix commits across agents** — each agent's work stays in its worktree
- **Announce identity on every switch** — always state which agent you are
- **Read the genome** — AGENTS.local.md contains your behavioral instructions
- **Each PR from its own branch** — the worktree branch is `agent/<Name>/work`
- **Source .env before wea/gh commands** — ensures correct WEA_AGENT

### Example

```
Operator: "Do 3 tasks as Cursor-1, then review task #5 as Claude-1"

AI: "Switching to Cursor-1@cursor"
    cd D:\GitHub\wetheagents-cursor-1
    [reads AGENTS.local.md]
    [does 3 tasks]

AI: "Switching to Claude-1@claude"
    cd D:\GitHub\wetheagents-claude-1
    [reads AGENTS.local.md]
    [reviews task #5]
```

---

## Parallel Execution (multiple terminals)

Each terminal opens a different worktree. No coordination needed —
git worktrees isolate branches by design.

### PowerShell Example

```powershell
# Terminal 1: Codex-2 works on task #42
cd D:\GitHub\wetheagents-codex-2
Get-Content .env | ForEach-Object {
  if ($_ -match '^\s*([^#=]+)=(.*)$') {
    [Environment]::SetEnvironmentVariable($matches[1], $matches[2].Trim(), 'Process')
  }
}
codex "Read AGENTS.local.md, then implement task #42"

# Terminal 2: Claude-1 reviews PR #15 (simultaneously)
cd D:\GitHub\wetheagents-claude-1
# source .env
claude "Read AGENTS.local.md, then review PR #15"
```

### Bash Example

```bash
# Terminal 1
cd /d/GitHub/wetheagents-codex-2
set -a; source .env; set +a
codex "Read AGENTS.local.md, then implement task #42"

# Terminal 2
cd /d/GitHub/wetheagents-claude-1
set -a; source .env; set +a
claude "Read AGENTS.local.md, then review PR #15"
```

---

## Adding a New Agent

Adding Cursor-2 (or any agent N+1):

```bash
# 1. Register in ledger (Agent0 does this on main)
# Add to balances.json: "Cursor-2@cursor": {"balance": 0, ...}

# 2. Create genome
mkdir genomes/Cursor-2@cursor
cp genomes/base/AGENTS.local.template.md genomes/Cursor-2@cursor/AGENTS.local.md
# Edit Role section, create genome_meta.json

# 3. Create worktree
cd D:\GitHub\wetheagents
git worktree add ../wetheagents-cursor-2 -b agent/Cursor-2/work main

# 4. Configure identity (requires extensions.worktreeConfig = true in main repo)
cd ../wetheagents-cursor-2
git config --worktree user.name "Cursor-2"
git config --worktree user.email "cursor-2@cursor"

# 5. Create .env
echo "WEA_AGENT=Cursor-2@cursor" > .env
echo "GITHUB_TOKEN=<PAT>" >> .env
echo "GITHUB_REPOSITORY=WeTheAgents/wetheagents" >> .env

# 6. Deploy genome
cp ../wetheagents/genomes/Cursor-2@cursor/AGENTS.local.md ./AGENTS.local.md
```

No code changes needed. All registration is data (JSON + worktree).

---

## Worktree Layout

```
D:\GitHub\
├── wetheagents/                   # main (Agent0 control center)
│   ├── genomes/                   # canonical genome storage
│   │   ├── base/                  # shared template + principles
│   │   ├── Cursor-1@cursor/       # per-agent canonical genome
│   │   ├── Codex-2@codex/
│   │   ├── Claude-1@claude/
│   │   └── gemini-4@google/
│   └── ledger/                    # economy (only Agent0 writes)
├── wetheagents-cursor-1/          # Cursor-1 worktree
│   ├── .env                       # WEA_AGENT + GITHUB_TOKEN
│   └── AGENTS.local.md            # working copy of genome
├── wetheagents-codex-2/           # Codex-2 worktree
├── wetheagents-claude-1/          # Claude-1 worktree
├── wetheagents-gemini-4/          # gemini-4 worktree
└── wetheagents-claude-17/         # Claude-17 worktree (Gauntlet Evaluator)
```

**Key design properties:**
- `genomes/` on main = canonical storage (committed, versioned)
- Worktree `AGENTS.local.md` = working copy (gitignored, may diverge)
- `wea genome snapshot` (future) = copy worktree genome back to `genomes/`
