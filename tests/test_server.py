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

class TestSkillsSearchPromoted:
    """Phase 2: Promoted skills must appear in /skills/search."""

    @pytest.fixture(autouse=True)
    def server(self):
        from engram.server import EngramServer
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            srv = EngramServer(
                persist_dir=tmpdir,
                host="127.0.0.1",
                port=0,
                auto_bootstrap=False,
            )
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
                pytest.fail("Server did not start in time")
            yield srv
            srv.stop()
            thread.join(timeout=5)

    def _url(self, server, path=""):
        return f"http://127.0.0.1:{server.port}{path}"

    def _post(self, server, path, body):
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            self._url(server, path), data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def test_skills_search_finds_promoted_skill(self, server):
        """Store a skill, promote it to L3, verify it appears in search."""
        # 1. Store skill with metadata
        result = self._post(server, "/remember", {
            "content": "How to build APKs with Capacitor and Gradle",
            "category": "skill",
            "importance": 0.7,
            "metadata": {"skill_name": "capacitor-apk-build", "skill_category": "devops"},
        })
        mem_id = result["memory_id"]

        # 2. Promote to L3: update access_count + run promote
        server.engram._semantic.collection.update(
            ids=[mem_id],
            metadatas=[{
                "category": "skill",
                "importance": 0.7,
                "access_count": 2,
                "skill_name": "capacitor-apk-build",
                "skill_category": "devops",
            }],
        )
        meta = server.engram._semantic.collection.get(ids=[mem_id], include=["metadatas"])
        server.engram._promote_memory(mem_id, meta["metadatas"][0], 0.7, 2)
        cat = server.engram._semantic.collection.get(ids=[mem_id], include=["metadatas"])["metadatas"][0]["category"]
        assert cat.startswith("L3_"), f"Promotion failed, category={cat}"

        # 3. Search — must find the promoted skill (was broken before: only looked at semantic_hits)
        result = self._post(server, "/skills/search", {"query": "APK build Gradle", "limit": 5})
        names = [s["name"] for s in result["skills"]]
        assert "capacitor-apk-build" in names, \
            f"Promoted skill missing from search. Found: {names}"

class TestCrashFixes:
    """Phase 4a/4b: Malformed JSON graceful handling and min_score default."""

    @pytest.fixture(autouse=True)
    def server(self):
        from engram.server import EngramServer
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            srv = EngramServer(
                persist_dir=tmpdir,
                host="127.0.0.1",
                port=0,
                auto_bootstrap=False,
            )
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
                pytest.fail("Server did not start in time")
            yield srv
            srv.stop()
            thread.join(timeout=5)

    def _url(self, server, path=""):
        return f"http://127.0.0.1:{server.port}{path}"

    def test_malformed_json_does_not_crash(self, server):
        """Sending raw non-JSON bytes returns an error, not a crash."""
        data = b"{not valid json at all!!!"
        req = urllib.request.Request(
            self._url(server, "/remember"),
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                body = resp.read()
                # Should get some HTTP response, not a connection drop
                assert resp.status in (200, 400, 500)
        except urllib.error.HTTPError as e:
            # Even an HTTP error means the server didn't crash
            assert e.code in (400, 500), f"Got unexpected HTTP {e.code}"

    def test_min_score_default_matches_engram(self, server):
        """Omitted min_score in /recall should use 0.3, not 0.5."""
        # Store a memory with specific technical content
        data = json.dumps({
            "content": "Quantum decoherence limits practical qubit gate fidelity to about 99.9% in superconducting circuits at 10 millikelvin",
            "category": "general",
        }).encode()
        req = urllib.request.Request(
            self._url(server, "/remember"), data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req):
            pass

        # Search for something in a completely different domain
        data = json.dumps({"query": "how to knit a wool scarf with cable stitch pattern"}).encode()
        req = urllib.request.Request(
            self._url(server, "/recall"), data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
        # At 0.3 threshold, should get it. At 0.5, would miss it.
        assert len(result["unified"]) > 0, \
            "Memory should be found at min_score=0.3 default"
        scores = [h["score"] for h in result["unified"]]
        # Verify we're in the 0.3-0.5 range (confirms the fix matters)
        assert any(0.3 <= s < 0.6 for s in scores), \
            f"Scores {scores} — got above 0.6; query is too similar to the stored content"

class TestSkillsIndexEnvVar:
    """Phase 5: ENGRAM_SKILLS_DIR is respected, not hardcoded fallback."""

    @pytest.fixture(autouse=True)
    def server(self):
        from engram.server import EngramServer
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            srv = EngramServer(
                persist_dir=tmpdir,
                host="127.0.0.1",
                port=0,
                auto_bootstrap=False,
            )
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
                pytest.fail("Server did not start in time")
            yield srv
            srv.stop()
            thread.join(timeout=5)

    def _url(self, server, path=""):
        return f"http://127.0.0.1:{server.port}{path}"

    def test_env_skills_dir_respected(self, server, monkeypatch):
        """Setting ENGRAM_SKILLS_DIR indexes from that directory."""
        import urllib.request, json, tempfile, os
        # Create a temp directory with a fake SKILL.md
        with tempfile.TemporaryDirectory() as skills_dir:
            os.makedirs(os.path.join(skills_dir, "test-category", "test-env-skill"))
            with open(os.path.join(skills_dir, "test-category", "test-env-skill", "SKILL.md"), "w") as f:
                f.write("""---
name: test-env-skill
description: A skill loaded from ENGRAM_SKILLS_DIR
---
# Test Env Skill

This is a test skill for verifying env var directory resolution.
""")
            monkeypatch.setenv("ENGRAM_SKILLS_DIR", skills_dir)

            data = json.dumps({}).encode()
            req = urllib.request.Request(
                self._url(server, "/skills/index"), data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read())
            assert result["status"] == "indexed"
            assert result["count"] >= 1, "Should find at least 1 skill from ENGRAM_SKILLS_DIR"
            assert result["skipped_duplicates"] == 0

            # Verify the skill is in the list
            data = json.dumps({"query": "test env skill"}).encode()
            req = urllib.request.Request(
                self._url(server, "/skills/search"), data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read())
            names = [s["name"] for s in result["skills"]]
            assert "test-env-skill" in names, f"Skill from ENGRAM_SKILLS_DIR not found: {names}"

class TestHTTPServerAttr:
    """Phase 6: HTTPServer._start_time no longer mutated."""

    @pytest.fixture(autouse=True)
    def server(self):
        from engram.server import EngramServer
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            srv = EngramServer(
                persist_dir=tmpdir,
                host="127.0.0.1",
                port=0,
                auto_bootstrap=False,
            )
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
                pytest.fail("Server did not start in time")
            yield srv
            srv.stop()
            thread.join(timeout=5)

    def test_no_start_time_on_stdlib_httpserver(self, server):
        """After server start/stop, stdlib HTTPServer class is clean."""
        from http.server import HTTPServer
        assert not hasattr(HTTPServer, "_start_time"), \
            "HTTPServer class should not have _start_time after server stop"


class TestSessionCompleteIdempotent:
    """Phase 9.1: /sessions/complete is idempotent (session_id dedup)."""

    @pytest.fixture(autouse=True)
    def server(self):
        from engram.server import EngramServer
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            srv = EngramServer(
                persist_dir=tmpdir,
                host="127.0.0.1",
                port=0,
                auto_bootstrap=False,
            )
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
                pytest.fail("Server did not start in time")
            yield srv
            srv.stop()
            thread.join(timeout=5)

    def _url(self, server, path=""):
        return f"http://127.0.0.1:{server.port}{path}"

    def _post(self, server, path, body):
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            self._url(server, path), data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def test_duplicate_session_id_returns_already_recorded(self, server):
        """Same session_id twice → second call returns already_recorded."""
        body = {
            "summary": "Test session summary A",
            "session_id": "sess-abc-123",
            "outcome": "completed",
            "timestamp": "2026-06-23T12:00:00",
        }

        # First call: should store
        r1 = self._post(server, "/sessions/complete", body)
        assert r1["status"] == "stored"
        mid1 = r1["memory_id"]

        # Second call: same session_id → already_recorded
        r2 = self._post(server, "/sessions/complete", body)
        assert r2["status"] == "already_recorded", f"Got {r2['status']}"
        assert r2["memory_id"] == mid1

        # Only one episodic memory should exist for this session
        items = server.engram._semantic.list_by_category("L4_", limit=100)
        session_items = [i for i in items
                        if (i.get("metadata", {}) or {}).get("session_id") == "sess-abc-123"]
        assert len(session_items) == 1, f"Expected 1, got {len(session_items)}"

    def test_different_session_ids_both_stored(self, server):
        """Different session_ids → both stored separately."""
        r1 = self._post(server, "/sessions/complete", {
            "summary": "Session one", "session_id": "sess-001",
        })
        r2 = self._post(server, "/sessions/complete", {
            "summary": "Session two", "session_id": "sess-002",
        })
        assert r1["status"] == "stored"
        assert r2["status"] == "stored"
        assert r1["memory_id"] != r2["memory_id"]

    def test_no_session_id_stores_both(self, server):
        """No session_id → both stored as separate entries (no dedup key)."""
        r1 = self._post(server, "/sessions/complete", {
            "summary": "Session A without id",
        })
        r2 = self._post(server, "/sessions/complete", {
            "summary": "Session A without id",  # same summary, no id
        })
        assert r1["status"] == "stored"
        assert r2["status"] == "stored"
        # Without session_id, nothing to deduplicate — both should store
        assert r1["memory_id"] != r2["memory_id"]


class TestSessionCountRobust:
    """Phase 9.2: total_sessions uses list_by_category, not exact-match recall."""

    @pytest.fixture(autouse=True)
    def server(self):
        from engram.server import EngramServer
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            srv = EngramServer(
                persist_dir=tmpdir,
                host="127.0.0.1",
                port=0,
                auto_bootstrap=False,
            )
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
                pytest.fail("Server did not start in time")
            yield srv
            srv.stop()
            thread.join(timeout=5)

    def _url(self, server, path=""):
        return f"http://127.0.0.1:{server.port}{path}"

    def _post(self, server, path, body):
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            self._url(server, path), data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def test_total_sessions_counts_variant_categories(self, server):
        """total_sessions counts L4 entries even with category drift."""
        # Store one via the API
        r1 = self._post(server, "/sessions/complete", {
            "summary": "API session", "session_id": "api-001",
        })
        assert r1["status"] == "stored"

        # Store one directly with a variant category (simulating future drift)
        server.engram._semantic.remember(
            content="Session: drift-001 | Outcome: completed | Drifted session",
            category="L4_episodic_session_promoted",  # variant category
            importance=0.75,
            metadata={"session_id": "drift-001", "source": "test"},
        )

        # Store a third via API
        r3 = self._post(server, "/sessions/complete", {
            "summary": "API session 3", "session_id": "api-003",
        })
        # total_sessions should count all 3 (L4 prefix, substring-aware)
        assert r3["total_sessions"] == 3, (
            f"Expected 3 sessions, got {r3['total_sessions']}"
        )


class TestRememberMetrics:
    """Phase 9.3: /metrics reports remember_total, remember_merged, merge_rate."""

    @pytest.fixture(autouse=True)
    def server(self):
        from engram.server import EngramServer
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            srv = EngramServer(
                persist_dir=tmpdir,
                host="127.0.0.1",
                port=0,
                auto_bootstrap=False,
            )
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
                pytest.fail("Server did not start in time")
            yield srv
            srv.stop()
            thread.join(timeout=5)

    def _url(self, server, path=""):
        return f"http://127.0.0.1:{server.port}{path}"

    def _post(self, server, path, body):
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            self._url(server, path), data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def test_metrics_reports_remember_merge_rate(self, server):
        """3 distinct + 2 duplicates → remember_total=5, merged=2, merge_rate=0.4."""
        # Reset metrics from other test classes (shared class-level state)
        from engram.server import _Handler
        _Handler._metrics_remembers.clear()

        # 3 distinct remembers
        for c in ["Alpha", "Beta", "Gamma"]:
            self._post(server, "/remember", {"content": c, "category": "test"})

        # 2 near-duplicates of "Alpha"
        self._post(server, "/remember", {"content": "Alpha", "category": "test"})
        self._post(server, "/remember", {"content": "Alpha", "category": "test"})

        with urllib.request.urlopen(self._url(server, "/metrics")) as resp:
            m = json.loads(resp.read())

        assert m["remember_total"] == 5, f"Got {m['remember_total']}"
        assert m["remember_merged"] == 2, f"Got {m['remember_merged']}"
        assert m["merge_rate"] == 0.4, f"Got {m['merge_rate']}"
