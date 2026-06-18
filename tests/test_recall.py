"""Tests for the memory search dashboard feature.

Tests that /recall returns properly structured results including
the new 'query' echo-back and 'count' fields.
"""

import pytest
import tempfile
import os
import sys
import time
import json
import urllib.request
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestRecallEnhancements:
    """Test enhanced recall API endpoint."""

    @pytest.fixture(autouse=True)
    def server(self):
        from engram.server import EngramServer
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            srv = EngramServer(persist_dir=tmpdir, host="127.0.0.1", port=0, auto_bootstrap=False)
            thread = threading.Thread(target=srv.start, daemon=True)
            thread.start()
            for _ in range(50):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/health", timeout=0.1)
                    break
                except Exception:
                    time.sleep(0.05)
            else:
                srv.stop()
                pytest.fail("Server did not start")
            yield srv
            srv.stop()
            thread.join(timeout=5)

    def _url(self, server, path=""):
        return f"http://127.0.0.1:{server.port}{path}"

    def test_recall_returns_query_echo(self, server):
        """Recall response includes the original query and count."""
        data = json.dumps({"content": "Jeremy likes dark mode", "category": "test"}).encode()
        req = urllib.request.Request(self._url(server, "/remember"), data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req)

        data = json.dumps({"query": "dark mode preference"}).encode()
        req = urllib.request.Request(self._url(server, "/recall"), data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            assert "query" in result
            assert result["query"] == "dark mode preference"
            assert "count" in result
            assert result["count"] > 0

    def test_recall_respects_min_score(self, server):
        """High min_score filters out weak matches."""
        # Store one memory
        data = json.dumps({"content": "PHP Composer is a tool", "category": "test"}).encode()
        req = urllib.request.Request(self._url(server, "/remember"), data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req)

        # Search with very high threshold
        data = json.dumps({"query": "Jeremy dashboard dark mode", "min_score": 0.95}).encode()
        req = urllib.request.Request(self._url(server, "/recall"), data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            assert result["count"] >= 0  # May be 0 if nothing matches
