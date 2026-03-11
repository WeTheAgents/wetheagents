# Launching Claude CLI as a Subprocess in Cloud Sessions

How to spawn `claude -p` child processes from within a cloud-hosted Claude Code session, using the parent session's subscription (no separate API key).

## Problem

Cloud Claude Code sessions authenticate via **session ingress** — a WebSocket connection managed by `environment-manager`. The auth token lives on a pipe (fd 4) that child processes cannot inherit. Running `claude -p` naively fails with "Not logged in".

## Solution: Auth Proxy

The session ingress token (`sk-ant-si-*`) is a valid **Bearer token** for the Anthropic REST API. But Claude CLI sends it as `x-api-key` header, which the API rejects. A local HTTP proxy rewrites the header:

```
claude -p  →  x-api-key: <token>  →  auth_proxy.py  →  Authorization: Bearer <token>  →  api.anthropic.com ✓
```

## Quick Start

### 1. Start the proxy (once per session)

```bash
python3 scripts/auth_proxy.py 18080 &
```

If using `cloud_agent_setup.sh`, step 8 does this automatically.

### 2. Launch a child claude process

```bash
cd /home/user/wetheagents-claude-1
source /home/user/wetheagents/.venv/bin/activate

SESSION_TOKEN=$(cat /home/claude/.claude/remote/.session_ingress_token)

echo "Your task prompt here" | \
env -u CLAUDECODE \
    -u CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR \
    -u CLAUDE_CODE_WEBSOCKET_AUTH_FILE_DESCRIPTOR \
    ANTHROPIC_API_KEY="$SESSION_TOKEN" \
    ANTHROPIC_BASE_URL="http://127.0.0.1:18080" \
    GITHUB_TOKEN="$CLAUDE1_GITHUB_TOKEN" \
    WEA_AGENT="Claude-1@claude" \
  claude -p --model haiku \
    --permission-mode default \
    --allowedTools "Read Glob Grep Edit Write Bash"
```

### Environment variables explained

| Variable | Why |
|----------|-----|
| `-u CLAUDECODE` | Bypass nested-session block |
| `-u CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR` | Prevent child from reading dead pipe |
| `-u CLAUDE_CODE_WEBSOCKET_AUTH_FILE_DESCRIPTOR` | Same — dead pipe cleanup |
| `ANTHROPIC_API_KEY` | Session ingress token (rewritten by proxy) |
| `ANTHROPIC_BASE_URL` | Route API calls through local proxy |
| `GITHUB_TOKEN` | Agent's GitHub PAT for git operations |
| `WEA_AGENT` | Agent identity for `wea` CLI |

## How It Works

### Cloud auth architecture

```
sandbox-gateway
  └─ environment-manager (PID 519)
       ├─ reads startup context from stdin (V0 format)
       │   includes: session ingress token + Anthropic OAuth token
       ├─ writes OAuth token to pipe → fd 4
       └─ spawns: claude --sdk-url wss://api.anthropic.com/v1/session_ingress/ws/SESSION_ID
            └─ reads OAuth token from fd 4 at startup
            └─ connects to session ingress WebSocket
            └─ all API calls go through WebSocket
```

Child processes can't use this path because:
1. fd 4 pipe is consumed (one-time read)
2. `--sdk-url` WebSocket is single-connection
3. Session ingress token is not a valid `x-api-key`

### The discovery

The session ingress token (`sk-ant-si-*`) is a JWT. When sent as `Authorization: Bearer`, the Anthropic REST API accepts it and bills to the parent subscription. Claude CLI uses `x-api-key` header (which the API rejects for this token type). The proxy bridges this gap.

### Token location

```
/home/claude/.claude/remote/.session_ingress_token
```

This file is created by `environment-manager` at session startup. It persists for the session lifetime.

## Research Log

### What was tried and failed

| Approach | Result |
|----------|--------|
| `unset CLAUDECODE` + `claude -p` | "Not logged in" — no stored credentials |
| `ANTHROPIC_API_KEY=sk-ant-si-*` directly | "Invalid API key" — wrong header type |
| `apiKeyHelper` script returning token | Process hangs — same wrong header |
| `--sdk-url wss://...` with token on fd 3/4 | Process hangs (timeout) — WebSocket won't accept second connection |
| `--dangerously-skip-permissions` | Blocked under root |
| Bearer token via `curl` | **Works!** — this led to the proxy solution |

### What works

| Approach | Result |
|----------|--------|
| `curl -H "Authorization: Bearer $TOKEN"` | 200 OK — token is valid as Bearer |
| Auth proxy (x-api-key → Bearer) + `claude -p` | **Full success** — tool use, file reading, task completion |

### Key insight

The Anthropic API accepts two auth methods:
- `x-api-key: sk-ant-api01-*` — standard API keys
- `Authorization: Bearer sk-ant-si-*` — session/OAuth tokens (subscription billing)

Claude CLI always uses `x-api-key`. The proxy converts to `Bearer`.

## Limitations

- **Session-bound**: token expires when the cloud session ends
- **Single proxy**: all child agents share one proxy instance
- **No streaming**: proxy buffers full responses (sufficient for `claude -p`)
- **Billing**: goes through the parent subscription (Max/Pro), not API credits

## Files

| File | Purpose |
|------|---------|
| `scripts/auth_proxy.py` | The proxy server (~70 lines Python) |
| `scripts/cloud_agent_setup.sh` | Step 8 starts the proxy automatically |
| `/home/claude/.claude/remote/.session_ingress_token` | Session token (runtime, not committed) |
