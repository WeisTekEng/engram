"""Phase 8: export.py safety gate + access_count type fix."""

import pytest
import tempfile
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestImportSafetyGate:
    """Phase 8.2: import_memories() dry-run gate."""

    def test_dry_run_does_not_clear(self):
        """confirm=False must NOT call clear() or modify the store."""
        from engram.export import import_memories
        from engram import Engram

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            eng = Engram(persist_dir=tmpdir, auto_bootstrap=False)

            # Populate with 3 memories
            eng.remember("Alpha", category="test")
            eng.remember("Beta", category="test")
            eng.remember("Gamma", category="test")
            assert eng._semantic.count() == 3

            # Dry-run import — must NOT modify
            fake_memories = [
                {"content": "X", "category": "test", "importance": 0.5},
                {"content": "Y", "category": "test", "importance": 0.5},
            ]
            result = import_memories(fake_memories, target_dir=tmpdir, confirm=False)
            assert result["dry_run"] is True
            assert result["would_import"] == 2
            assert result["existing_memories"] == 3

            # Store must be completely unchanged
            assert eng._semantic.count() == 3

    def test_confirm_actually_imports(self):
        """confirm=True clears and imports the new data."""
        from engram.export import import_memories
        from engram import Engram

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            eng = Engram(persist_dir=tmpdir, auto_bootstrap=False)

            # Populate, then import over it
            eng.remember("Old data", category="test")
            assert eng._semantic.count() == 1

            fake_memories = [
                {"content": "New A", "category": "test", "importance": 0.8},
                {"content": "New B", "category": "test", "importance": 0.9},
            ]
            result = import_memories(fake_memories, target_dir=tmpdir, confirm=True)
            assert result["dry_run"] is False
            assert result["imported"] == 2

            # Old data gone, new data present
            # Re-open to avoid stale reference
            eng2 = Engram(persist_dir=tmpdir, auto_bootstrap=False)
            assert eng2._semantic.count() == 2

    def test_full_round_trip(self):
        """Export → clear → import round trip preserves data."""
        from engram.export import export_memories, import_memories
        from engram import Engram

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            eng = Engram(persist_dir=tmpdir, auto_bootstrap=False)

            eng.remember("Jeremy prefers dark mode", category="user_preference", importance=0.9)
            eng.remember("Buckets uses port 5174", category="environment", importance=0.85)
            orig_count = eng._semantic.count()
            assert orig_count == 2

            # Export
            exported = export_memories(eng)

            # Import into same dir (round-trip)
            result = import_memories(exported, target_dir=tmpdir, confirm=True)
            assert result["imported"] == orig_count

            # Verify
            eng2 = Engram(persist_dir=tmpdir, auto_bootstrap=False)
            assert eng2._semantic.count() == orig_count

            # Spot-check content
            recall = eng2.recall("dark mode", limit=1)
            assert len(recall.unified) > 0
            assert "dark mode" in recall.unified[0]["content"].lower()


class TestAccessCountType:
    """Phase 8.3: access_count must survive import as int, not str."""

    def test_access_count_is_int_after_import(self):
        """Import must write access_count as int, not str."""
        from engram.export import export_memories, import_memories
        from engram import Engram

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir_src:
            eng_src = Engram(persist_dir=tmpdir_src, auto_bootstrap=False)

            # Store with known access_count
            mem_id = eng_src.remember("Frequently accessed fact", category="general", importance=0.7)

            # Set access_count directly on the semantic index
            eng_src._semantic.collection.update(
                ids=[mem_id],
                metadatas=[{"category": "general", "importance": 0.7, "access_count": 5}],
            )

            # Export
            exported = export_memories(eng_src)

            # Import into fresh store
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir_dst:
                result = import_memories(exported, target_dir=tmpdir_dst, confirm=True)
                assert result["imported"] == 1

                eng_dst = Engram(persist_dir=tmpdir_dst, auto_bootstrap=False)
                raw = eng_dst._semantic.collection.get(include=["metadatas"])

                # THIS is the key assertion — must be int, not str
                ac = raw["metadatas"][0].get("access_count", 0)
                assert isinstance(ac, int), (
                    f"access_count should be int, got {type(ac).__name__}: {ac!r}"
                )
                assert ac == 5
