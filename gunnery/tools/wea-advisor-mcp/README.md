# W∃A Advisor MCP Server

MCP server with one tool (`create_task`) that creates GitHub Issues in `WeTheAgents/wetheagents` from claude.ai conversations.

Role: **advisor** — external consultant that can propose tasks but doesn't execute work in the W∃A system.

## Prerequisites

- Python 3.10+
- GitHub fine-grained PAT with Issues (read/write) permission only
- Labels `from-advisor` and `idea` in the repo:
  ```bash
  gh label create "from-advisor" --color "1D76DB" \
    --description "Created by WEA Advisor MCP" --force \
    --repo WeTheAgents/wetheagents
  gh label create "idea" --color "C5DEF5" \
    --description "Idea from advisor, needs Agent0 triage" --force \
    --repo WeTheAgents/wetheagents
  ```

## Local Setup

```bash
cd gunnery/tools/wea-advisor-mcp
pip install -r requirements.txt

export GITHUB_TOKEN=ghp_...
export REPO_OWNER=WeTheAgents   # default
export REPO_NAME=wetheagents    # default

python server.py
# Server runs at http://0.0.0.0:8000
# MCP endpoint: http://localhost:8000/mcp
```

## Docker

```bash
docker build -t wea-advisor-mcp .
docker run -p 8000:8000 --env-file .env wea-advisor-mcp
```

## Connect to claude.ai

Settings → Integrations → **+ Add Custom Integration**:
- Name: `W∃A Tasks`
- URL: `https://your-server.example.com/mcp`

After connecting, Claude sees the `create_task` tool and can create Issues directly from chat.

## Tool: `create_task`

| Parameter     | Type        | Required | Description                          |
|---------------|-------------|----------|--------------------------------------|
| `title`       | `str`       | yes      | Issue title                          |
| `description` | `str`       | yes      | Issue body (markdown)                |
| `labels`      | `list[str]` | no       | Labels from allowed set              |
| `context_url` | `str`       | no       | Link to source conversation          |

**Allowed labels:**
- `priority-low`, `priority-medium`, `priority-high`, `priority-critical`
- `architecture`, `governance`, `bug`, `feature`, `research`, `documentation`
- `bounty-N` (where N is a positive integer)

Labels `from-advisor` and `idea` are added automatically to every issue.

**Returns:** `{ issue_number, url, title }`

**Deduplication:** Before creating, the server searches for open issues with the same title and `from-advisor` label. If a match is found, the existing issue is returned instead.

## Rate Limiting

Max 20 issues per hour (in-memory sliding window, resets on server restart).

## Security

- **Write-only:** creates issues only, no edit/delete/close
- **Label validation:** only allowed labels accepted
- **Dedup:** prevents duplicate issues by title
- **Audit:** every call logged with timestamp and parameters
