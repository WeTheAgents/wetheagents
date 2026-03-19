#!/usr/bin/env python3
"""Multi-provider streaming auth proxy for cloud agent orchestration.

Routes API requests by path prefix to the correct provider, transforms auth
headers, and streams responses (SSE) without buffering.

Routing:
    /anthropic/v1/...  → api.anthropic.com/v1/...
    /openai/v1/...     → api.openai.com/v1/...
    /gemini/v1beta/... → generativelanguage.googleapis.com/v1beta/...
    /v1/messages       → api.anthropic.com/v1/messages  (backward compat)
    /health            → {"status":"ok","providers":[...]}

Auth priority per provider: env API key → subscription rewrite → passthrough.

Usage:
    python3 auth_proxy.py [PORT]       # default: 18080

See docs/cloud_subprocess_launch.md for launch examples.
"""

import http.client
import http.server
import json
import os
import socket
import socketserver
import ssl
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18080

# ── Auth transforms ──────────────────────────────────────────


def anthropic_auth(headers: dict) -> dict:
    """Anthropic: env key passthrough, or sk-ant-si-* → Bearer rewrite."""
    env_key = os.environ.get("ANTHROPIC_PROXY_API_KEY")
    if env_key:
        headers["x-api-key"] = env_key
        return headers
    api_key = headers.pop("x-api-key", None)
    if api_key and api_key.startswith("sk-ant-si"):
        headers["authorization"] = f"Bearer {api_key}"
    elif api_key:
        headers["x-api-key"] = api_key
    return headers


def openai_auth(headers: dict) -> dict:
    """OpenAI: env key → Bearer, or passthrough client header.

    Only uses explicitly-configured OPENAI_API_KEY env var.
    Does NOT auto-inject credentials from local files — the proxy is a shared
    localhost service, and any local process could otherwise use operator creds.
    """
    env_key = os.environ.get("OPENAI_API_KEY")
    if env_key:
        headers["authorization"] = f"Bearer {env_key}"
    return headers


def gemini_auth(headers: dict) -> dict:
    """Gemini: env key → x-goog-api-key."""
    env_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if env_key:
        headers["x-goog-api-key"] = env_key
    return headers


# ── Provider registry ────────────────────────────────────────

PROVIDERS = {
    "anthropic": {"target": "api.anthropic.com", "transform": anthropic_auth},
    "openai": {"target": "api.openai.com", "transform": openai_auth},
    "gemini": {
        "target": "generativelanguage.googleapis.com",
        "transform": gemini_auth,
    },
}

# ── SSL context (shared, thread-safe) ────────────────────────

_SSL_CTX = ssl.create_default_context()

# ── Proxy handler ────────────────────────────────────────────

CHUNK_SIZE = 8192


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    """Routes, transforms auth, and streams responses."""

    # HTTP/1.1 required for Transfer-Encoding: chunked and SSE streaming.
    # BaseHTTPRequestHandler defaults to HTTP/1.0 which doesn't support chunked.
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path == "/health":
            body = json.dumps(
                {"status": "ok", "providers": sorted(PROVIDERS)}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._proxy("GET")

    def do_POST(self):
        self._proxy("POST")

    def do_PUT(self):
        self._proxy("PUT")

    def do_DELETE(self):
        self._proxy("DELETE")

    def do_PATCH(self):
        self._proxy("PATCH")

    # ── Core proxy logic ─────────────────────────────────────

    def _proxy(self, method: str):
        provider, remote_path = self._resolve_route()
        if provider is None:
            self._error(404, f"No route for {self.path}")
            return

        cfg = PROVIDERS[provider]
        target = cfg["target"]

        # Collect headers (lowercase keys, skip hop-by-hop)
        skip = {"host", "transfer-encoding", "connection"}
        hdrs: dict[str, str] = {}
        for key, val in self.headers.items():
            if key.lower() not in skip:
                hdrs[key.lower()] = val

        # Auth transform
        cfg["transform"](hdrs)

        # Read request body
        body = None
        cl = int(self.headers.get("Content-Length", 0))
        if cl > 0:
            body = self.rfile.read(cl)

        # Connect to upstream
        try:
            conn = http.client.HTTPSConnection(target, context=_SSL_CTX, timeout=300)  # nosemgrep: httpsconnection-detected
            conn.request(method, remote_path, body=body, headers=hdrs)
            resp = conn.getresponse()
        except Exception as exc:
            self._error(502, str(exc))
            return

        # Forward status + headers
        self.send_response(resp.status)
        chunked = False
        for key, val in resp.getheaders():
            lk = key.lower()
            if lk in ("connection",):
                continue
            if lk == "transfer-encoding" and "chunked" in val.lower():
                chunked = True
                continue  # we'll stream without TE header
            self.send_header(key, val)

        content_type = resp.getheader("content-type", "")
        is_stream = "text/event-stream" in content_type or chunked
        if is_stream:
            self.send_header("Transfer-Encoding", "chunked")
        elif not resp.getheader("content-length"):
            # HTTP/1.1 needs a body termination signal. Without Content-Length
            # or chunked encoding, close the connection to signal end-of-body.
            self.send_header("Connection", "close")
        self.end_headers()

        # Stream response
        try:
            if is_stream:
                while True:
                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    self.wfile.write(b"%x\r\n%b\r\n" % (len(chunk), chunk))
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            else:
                while True:
                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        finally:
            conn.close()

    # ── Route resolution ─────────────────────────────────────

    def _resolve_route(self) -> tuple:
        """Return (provider_name, remote_path) or (None, None)."""
        path = self.path
        for name in PROVIDERS:
            prefix = f"/{name}/"
            if path.startswith(prefix):
                return name, "/" + path[len(prefix):]
        # Backward compat: bare /v1/messages → anthropic
        if path.startswith("/v1/"):
            return "anthropic", path
        return None, None

    # ── Helpers ──────────────────────────────────────────────

    def _error(self, code: int, msg: str):
        body = json.dumps({"error": msg}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # Silent — avoid polluting agent stdout


# ── Threaded server ──────────────────────────────────────────


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    address_family = socket.AF_INET


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), ProxyHandler)
    providers = ", ".join(sorted(PROVIDERS))
    print(
        f"auth-proxy listening on http://127.0.0.1:{PORT} "
        f"[providers: {providers}]",
        flush=True,
    )
    server.serve_forever()
