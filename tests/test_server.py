"""Tests for the Engram HTTP server (daemon).

Tests the REST API that keeps Engram alive and accessible.
"""

import pytest
import tempfile
import os
import sys
import time
import json
import urllib.request
import urllib.error
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestEngramServer:
    """Test the Engram HTTP server REST API."""

    @pytest.fixture(autouse=True)
    def server(self):
        """Start a test Engram server on a random port."""
        from engram.server import EngramServer

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            srv = EngramServer(
                persist_dir=tmpdir,
                host="127.0.0.1",
                port=0,  # Random port
                auto_bootstrap=False,
            )
            # Start in background thread
            thread = threading.Thread(target=srv.start, daemon=True)
            thread.start()

            # Wait for server to be ready
            for _ in range(50):
                try:
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{srv.port}/health", timeout=0.1
                    )
                    break
                except Exception:
                    time.sleep(0.05)
            else:
                srv.stop()
                pytest.fail("Server did not start in time")

            yield srv

            srv.stop()
            thread.join(timeout=5)

    def _url(self, server, path=""):
        return f"http://127.0.0.1:{server.port}{path}"

    def test_health_endpoint(self, server):
        """Health check returns OK with status."""
        with urllib.request.urlopen(self._url(server, "/health")) as resp:
            data = json.loads(resp.read())
            assert data["status"] == "ok"
            assert "layers" in data

    def test_remember_and_stats(self, server):
        """POST /remember stores a memory, GET /stats shows it."""
        # Store a memory
        data = json.dumps({
            "content": "Jeremy prefers dark mode",
            "category": "user_preference",
            "importance": 0.9,
        }).encode()
        req = urllib.request.Request(
            self._url(server, "/remember"),
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            assert result["status"] == "stored"
            assert "memory_id" in result

        # Check stats reflect it
        with urllib.request.urlopen(self._url(server, "/stats")) as resp:
            stats = json.loads(resp.read())
            assert stats["semantic_index"]["total_memories"] == 1

    def test_recall(self, server):
        """POST /recall returns relevant memories."""
        # Store memories first
        for content, cat in [
            ("Jeremy prefers dark mode on dashboards", "user_preference"),
            ("Buckets app uses Tailscale on port 5174", "environment"),
            ("PHP Composer is a package manager", "general"),
        ]:
            data = json.dumps({"content": content, "category": cat}).encode()
            req = urllib.request.Request(
                self._url(server, "/remember"),
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req):
                pass  # Consume response

        # Recall
        data = json.dumps({"query": "dashboard theme preference"}).encode()
        req = urllib.request.Request(
            self._url(server, "/recall"),
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            assert "semantic_hits" in result
            assert len(result["semantic_hits"]) > 0
            assert "dark mode" in result["semantic_hits"][0]["content"].lower()

    def test_forget(self, server):
        """POST /forget removes a memory."""
        # Store
        data = json.dumps({"content": "Temporary memory"}).encode()
        req = urllib.request.Request(
            self._url(server, "/remember"),
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            memory_id = json.loads(resp.read())["memory_id"]

        # Forget
        data = json.dumps({"memory_id": memory_id}).encode()
        req = urllib.request.Request(
            self._url(server, "/forget"),
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            assert result["status"] == "deleted"

        # Verify gone
        with urllib.request.urlopen(self._url(server, "/stats")) as resp:
            stats = json.loads(resp.read())
            assert stats["semantic_index"]["total_memories"] == 0

    def test_layers_endpoint(self, server):
        """GET /layers returns status of all layers."""
        with urllib.request.urlopen(self._url(server, "/layers")) as resp:
            data = json.loads(resp.read())
            assert "layers" in data
            layer_ids = [l["id"] for l in data["layers"]]
            assert 1 in layer_ids  # Hot Cache
            assert 2 in layer_ids  # Semantic Index

    def test_dashboard_served(self, server):
        """GET /dashboard returns HTML."""
        with urllib.request.urlopen(self._url(server, "/dashboard")) as resp:
            assert resp.status == 200
            content_type = resp.headers.get("Content-Type", "")
            assert "text/html" in content_type
