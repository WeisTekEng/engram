"""Tests for Engram core and Semantic Index."""

import pytest
import tempfile
import os
import sys

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSemanticIndex:
    """Test Layer 2: Semantic Index with ChromaDB."""

    def test_remember_and_count(self):
        from engram.layers.semantic_index import SemanticIndex
        with tempfile.TemporaryDirectory() as tmpdir:
            index = SemanticIndex(persist_dir=tmpdir)
            assert index.count() == 0

            id1 = index.remember("Jeremy prefers dark mode", category="user_preference")
            assert index.count() == 1
            assert len(id1) == 16  # SHA256 truncated

    def test_recall_finds_relevant(self):
        from engram.layers.semantic_index import SemanticIndex
        with tempfile.TemporaryDirectory() as tmpdir:
            index = SemanticIndex(persist_dir=tmpdir)

            index.remember("Jeremy prefers dark mode on all dashboards", category="user_preference", importance=0.9)
            index.remember("The Buckets app uses Tailscale on port 5174", category="environment")
            index.remember("PHP Composer is a package manager", category="general")

            results = index.recall("What theme does Jeremy like for dashboards?")
            assert len(results) > 0
            # The dark mode memory should be top hit
            assert "dark mode" in results[0].memory.content.lower()
            assert results[0].score > 0.3

    def test_recall_irrelevant_scores_low(self):
        from engram.layers.semantic_index import SemanticIndex
        with tempfile.TemporaryDirectory() as tmpdir:
            index = SemanticIndex(persist_dir=tmpdir)

            index.remember("Jeremy likes dark mode", category="user_preference")
            index.remember("Use port 5174 for Tailscale", category="environment")

            # Search for something completely different
            results = index.recall("How to bake a chocolate cake?")
            # Either returns nothing or has low scores
            for r in results:
                assert r.score < 0.7  # Shouldn't be super confident

    def test_forget(self):
        from engram.layers.semantic_index import SemanticIndex
        with tempfile.TemporaryDirectory() as tmpdir:
            index = SemanticIndex(persist_dir=tmpdir)
            memory_id = index.remember("Test memory")
            assert index.count() == 1
            assert index.forget(memory_id)
            assert index.count() == 0

    def test_persistence(self):
        from engram.layers.semantic_index import SemanticIndex
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create and add
            index1 = SemanticIndex(persist_dir=tmpdir)
            index1.remember("Persistent memory test")
            del index1

            # Reopen and verify
            index2 = SemanticIndex(persist_dir=tmpdir)
            assert index2.count() == 1

    def test_batch_remember(self):
        from engram.layers.semantic_index import SemanticIndex
        with tempfile.TemporaryDirectory() as tmpdir:
            index = SemanticIndex(persist_dir=tmpdir)
            ids = index.batch_remember([
                {"content": "Memory A", "category": "test"},
                {"content": "Memory B", "category": "test"},
                {"content": "Memory C", "category": "test"},
            ])
            assert len(ids) == 3
            assert index.count() == 3

    def test_category_filter(self):
        from engram.layers.semantic_index import SemanticIndex
        with tempfile.TemporaryDirectory() as tmpdir:
            index = SemanticIndex(persist_dir=tmpdir)
            index.remember("Dark mode preference", category="user_preference")
            index.remember("Tailscale IP 100.104.70.8", category="environment")
            index.remember("PostgreSQL 16 for database", category="environment")

            results = index.recall("network config", category_filter="environment")
            assert len(results) > 0
            for r in results:
                assert r.memory.category == "environment"


class TestTokenBudget:
    """Test token budget allocation."""

    def test_allocation(self):
        from engram.utils.token_budget import TokenBudget
        budget = TokenBudget(max_chars=2000)
        allocs = budget.allocate()
        assert len(allocs) == 5
        assert sum(a.allocated_chars for a in allocs) == 2000

    def test_consume_and_report(self):
        from engram.utils.token_budget import TokenBudget
        budget = TokenBudget(max_chars=1000)
        budget.allocate()
        
        # Layer 2 gets 60% = 600 chars
        assert budget.consume(2, 200)  # Should fit
        assert not budget.consume(2, 500)  # Should exceed

        report = budget.report()
        assert report["max_chars"] == 1000
        assert report["total_used"] == 200


class TestEngramCore:
    """Test the main Engram orchestrator."""

    def test_remember_and_recall(self):
        from engram import Engram
        with tempfile.TemporaryDirectory() as tmpdir:
            engram = Engram(persist_dir=tmpdir, auto_bootstrap=False)

            engram.remember("Jeremy prefers dark mode", category="user_preference", importance=0.9)
            engram.remember("Buckets app runs on port 5174", category="environment")

            recall = engram.recall("dashboard theme preference")
            assert len(recall.semantic_hits) > 0

    def test_hot_cache(self):
        from engram import Engram
        with tempfile.TemporaryDirectory() as tmpdir:
            engram = Engram(persist_dir=tmpdir, auto_bootstrap=False)

            engram.remember("Current task: refactoring dashboard", layer=1)
            engram.remember("Active branch: feat/react-refactor", layer=1)

            recall = engram.recall("any query", layers=[1])
            assert len(recall.hot_cache) > 0

    def test_format_for_prompt(self):
        from engram import Engram
        from engram.utils.token_budget import TokenBudget
        with tempfile.TemporaryDirectory() as tmpdir:
            engram = Engram(persist_dir=tmpdir, auto_bootstrap=False)

            engram.remember("Jeremy prefers dark mode", category="user_preference")
            engram.remember("Active task: refactor", layer=1)

            recall = engram.recall("dashboard theme")
            budget = TokenBudget(max_chars=2000)
            formatted = recall.format_for_prompt(budget)

            assert isinstance(formatted, str)
            assert len(formatted) > 0

    def test_stats(self):
        from engram import Engram
        with tempfile.TemporaryDirectory() as tmpdir:
            engram = Engram(persist_dir=tmpdir, auto_bootstrap=False)
            engram.remember("test memory")
            stats = engram.stats()
            assert "semantic_index" in stats
            assert stats["semantic_index"]["total_memories"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
