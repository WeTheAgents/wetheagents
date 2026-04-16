from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from scripts import auth_proxy


def _start_server():
    server = auth_proxy.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        auth_proxy.ProxyHandler,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_server(server, thread):
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


def _request(port: int, path: str, token: str | None = None):
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers=headers,
    )
    return urllib.request.urlopen(request, timeout=2)


def test_health_requires_bearer_token(monkeypatch):
    monkeypatch.setattr(auth_proxy, "_BEARER_TOKEN", "test-token")
    server, thread = _start_server()
    port = server.server_address[1]
    try:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _request(port, "/health")
        assert exc_info.value.code == 401
        assert exc_info.value.headers["WWW-Authenticate"] == (
            'Bearer realm="auth-proxy"'
        )

        with _request(port, "/health", "test-token") as response:
            assert response.status == 200
            body = json.loads(response.read())
        assert body["status"] == "ok"
        assert body["providers"] == ["anthropic", "gemini", "openai"]
    finally:
        _stop_server(server, thread)


def test_proxy_authorization_header_is_not_forwarded(monkeypatch):
    monkeypatch.setattr(auth_proxy, "_BEARER_TOKEN", "test-token")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    captured = {}

    class FakeResponse:
        status = 204

        def getheaders(self):
            return [("Content-Length", "0")]

        def getheader(self, name, default=None):
            if name.lower() == "content-length":
                return "0"
            return default

        def read(self, _size=-1):
            return b""

    class FakeConnection:
        def __init__(self, target, context=None, timeout=None):
            captured["target"] = target

        def request(self, method, path, body=None, headers=None):
            captured["method"] = method
            captured["path"] = path
            captured["body"] = body
            captured["headers"] = headers

        def getresponse(self):
            return FakeResponse()

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(auth_proxy.http.client, "HTTPSConnection", FakeConnection)

    server, thread = _start_server()
    port = server.server_address[1]
    try:
        with _request(port, "/openai/v1/models", "test-token") as response:
            assert response.status == 204
    finally:
        _stop_server(server, thread)

    assert captured["target"] == "api.openai.com"
    assert captured["method"] == "GET"
    assert captured["path"] == "/v1/models"
    assert "authorization" not in captured["headers"]
    assert captured["closed"] is True
