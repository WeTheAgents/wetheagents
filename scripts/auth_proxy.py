#!/usr/bin/env python3
"""Auth proxy for Claude CLI subprocess launches in cloud sessions.

Cloud-hosted Claude Code sessions authenticate via session ingress tokens
(sk-ant-si-*). These tokens are valid Bearer tokens for the Anthropic API,
but Claude CLI sends them as x-api-key headers, which the API rejects.

This proxy rewrites: x-api-key → Authorization: Bearer

Usage:
    python3 auth_proxy.py [PORT]       # default: 18080

Then launch child claude processes with:
    ANTHROPIC_API_KEY="$(cat /home/claude/.claude/remote/.session_ingress_token)" \
    ANTHROPIC_BASE_URL="http://127.0.0.1:18080" \
    claude -p --model haiku "prompt"

See docs/cloud_subprocess_launch.md for full details.
"""

import http.server
import json
import ssl
import sys
import urllib.request

TARGET = "https://api.anthropic.com"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18080


class AuthProxyHandler(http.server.BaseHTTPRequestHandler):
    """Rewrites x-api-key to Authorization: Bearer and forwards to Anthropic."""

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        headers = {}
        for key, val in self.headers.items():
            lower = key.lower()
            if lower == "x-api-key":
                headers["Authorization"] = f"Bearer {val}"
            elif lower == "host":
                continue
            else:
                headers[key] = val

        url = f"{TARGET}{self.path}"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")

        try:
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, context=ctx, timeout=300) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                for key, val in resp.getheaders():
                    if key.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(key, val)
                self.end_headers()
                self.wfile.write(resp_body)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def log_message(self, format, *args):
        pass  # Silent — avoid polluting agent stdout


if __name__ == "__main__":
    server = http.server.HTTPServer(("127.0.0.1", PORT), AuthProxyHandler)
    print(f"auth-proxy listening on http://127.0.0.1:{PORT}", flush=True)
    server.serve_forever()
