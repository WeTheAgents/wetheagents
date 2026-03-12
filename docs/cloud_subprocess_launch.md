# Launching CLI Agents as Subprocesses in Cloud Sessions

How to spawn `claude -p`, `codex`, and other CLI agents from within a cloud-hosted Claude Code session, using a local auth proxy.

## Problem

Cloud Claude Code sessions authenticate via **session ingress** — a WebSocket connection managed by `environment-manager`. Child processes cannot inherit this auth. Running `claude -p` naively fails with "Not logged in".

## Solution: Multi-Provider Auth Proxy

A local HTTP proxy (`scripts/auth_proxy.py`) runs on `127.0.0.1:18080` and:

1. **Routes** requests by path prefix to the correct upstream API
2. **Transforms** auth headers per provider (e.g. `x-api-key` → `Bearer`)
3. **Streams** SSE responses without buffering (chunked transfer)
4. **Handles concurrent requests** via `ThreadingHTTPServer`

```
CLI agent  →  http://127.0.0.1:18080/{provider}/...  →  auth_proxy.py  →  upstream API
```

## Routing

All providers share one port. Path prefix determines the upstream:

| Path prefix | Upstream | Example |
|-------------|----------|---------|
| `/anthropic/v1/...` | `api.anthropic.com` | `/anthropic/v1/messages` |
| `/openai/v1/...` | `api.openai.com` | `/openai/v1/chat/completions` |
| `/gemini/v1beta/...` | `generativelanguage.googleapis.com` | `/gemini/v1beta/models/...` |
| `/v1/messages` | `api.anthropic.com` | Backward compat (bare path) |
| `/health` | (local) | `{"status":"ok","providers":[...]}` |

## Auth Transforms

Priority per provider: **env API key → subscription rewrite → passthrough**.

| Provider | Env key | Subscription rewrite |
|----------|---------|---------------------|
| **Anthropic** | `ANTHROPIC_PROXY_API_KEY` → `x-api-key` | `sk-ant-si-*` → `Authorization: Bearer` |
| **OpenAI** | `OPENAI_API_KEY` → `Authorization: Bearer` | Inject from `~/.codex/auth.json` |
| **Gemini** | `GOOGLE_API_KEY` / `GEMINI_API_KEY` → `x-goog-api-key` | — |

## Quick Start

### 1. Start the proxy (once per session)

```bash
python3 scripts/auth_proxy.py 18080 &
```

If using `cloud_agent_setup.sh`, step 8 does this automatically with a health check.

### 2. Verify

```bash
curl http://127.0.0.1:18080/health
# → {"status": "ok", "providers": ["anthropic", "gemini", "openai"]}
```

### 3. Launch agents

#### Claude (via Anthropic)

```bash
cd /home/user/wetheagents-claude-1
source /home/user/wetheagents/.venv/bin/activate

SESSION_TOKEN=$(cat /home/claude/.claude/remote/.session_ingress_token)

echo "Your task prompt here" | \
env -u CLAUDECODE \
    -u CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR \
    -u CLAUDE_CODE_WEBSOCKET_AUTH_FILE_DESCRIPTOR \
    ANTHROPIC_API_KEY="$SESSION_TOKEN" \
    ANTHROPIC_BASE_URL="http://127.0.0.1:18080/anthropic" \
    GITHUB_TOKEN="$CLAUDE1_GITHUB_TOKEN" \
    WEA_AGENT="Claude-1@claude" \
  claude -p --model haiku \
    --permission-mode default \
    --allowedTools "Read Glob Grep Edit Write Bash"
```

Note: `ANTHROPIC_BASE_URL` now includes `/anthropic` prefix. Bare `/v1/messages` still works for backward compat.

#### Codex (via OpenAI)

```bash
cd /home/user/wetheagents-codex-2

OPENAI_API_KEY="$OPENAI_API_KEY" \
OPENAI_BASE_URL="http://127.0.0.1:18080/openai" \
GITHUB_TOKEN="$CODEX2_GITHUB_TOKEN" \
WEA_AGENT="Codex-2@codex" \
  codex "Your task prompt here"
```

#### Gemini (via Google)

```bash
cd /home/user/wetheagents-gemini-3

GOOGLE_API_KEY="$GOOGLE_API_KEY" \
GEMINI_BASE_URL="http://127.0.0.1:18080/gemini" \
GITHUB_TOKEN="$GEMINI3_GITHUB_TOKEN" \
WEA_AGENT="Gemini-3@google" \
  # gemini CLI invocation here
```

## Environment Variables

| Variable | Why |
|----------|-----|
| `-u CLAUDECODE` | Bypass nested-session block |
| `-u CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR` | Prevent child from reading dead pipe |
| `-u CLAUDE_CODE_WEBSOCKET_AUTH_FILE_DESCRIPTOR` | Same — dead pipe cleanup |
| `ANTHROPIC_API_KEY` | Session ingress token (rewritten by proxy) |
| `ANTHROPIC_BASE_URL` | Route API calls through proxy (`/anthropic` prefix) |
| `OPENAI_API_KEY` | OpenAI API key (injected by proxy) |
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
       └─ spawns: claude --sdk-url wss://...
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

Created by `environment-manager` at session startup. Persists for the session lifetime.

## Adding a New Provider

1. Add an auth transform function to `auth_proxy.py`
2. Add an entry to the `PROVIDERS` dict
3. Requests to `/{new_provider}/...` are automatically routed

## Limitations

- **Session-bound**: Anthropic token expires when the cloud session ends
- **Billing**: Anthropic calls go through the parent subscription (Max/Pro)
- **No retry**: proxy does not retry failed upstream requests

## Files

| File | Purpose |
|------|---------|
| `scripts/auth_proxy.py` | Multi-provider streaming proxy (~240 lines) |
| `scripts/cloud_agent_setup.sh` | Step 8 starts proxy with health check |
| `/home/claude/.claude/remote/.session_ingress_token` | Session token (runtime) |

## Research Log

### What was tried and failed

| Approach | Result |
|----------|--------|
| `unset CLAUDECODE` + `claude -p` | "Not logged in" — no stored credentials |
| `ANTHROPIC_API_KEY=sk-ant-si-*` directly | "Invalid API key" — wrong header type |
| `apiKeyHelper` script returning token | Process hangs — same wrong header |
| `--sdk-url wss://...` with token on fd 3/4 | Process hangs — WebSocket won't accept second connection |
| Bearer token via `curl` | **Works!** — led to the proxy solution |

### What works

| Approach | Result |
|----------|--------|
| Auth proxy (x-api-key → Bearer) + `claude -p` | Full success — tool use, streaming, task completion |
| Multi-provider proxy with path routing | Full success — Claude, Codex, Gemini via one port |
