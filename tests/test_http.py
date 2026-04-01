"""Tests for HTTP endpoints (no spacemouse needed)."""

from fastapi.testclient import TestClient

from spacenav_ws.main import app


client = TestClient(app)


class TestNlproxyEndpoint:
    def test_returns_port_and_version(self):
        resp = client.get("/3dconnexion/nlproxy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["port"] == 8181
        assert "version" in data

    def test_homepage_returns_html(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Mouse Stream" in resp.text
