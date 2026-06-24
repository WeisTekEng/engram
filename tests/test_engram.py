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

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:

            index = SemanticIndex(persist_dir=tmpdir)

            assert index.count() == 0



            id1 = index.remember("Jeremy prefers dark mode", category="user_preference")

            assert index.count() == 1

            assert len(id1) == 16  # SHA256 truncated



    def test_recall_finds_relevant(self):

        from engram.layers.semantic_index import SemanticIndex

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:

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

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:

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

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:

            index = SemanticIndex(persist_dir=tmpdir)

            memory_id = index.remember("Test memory")

            assert index.count() == 1

            assert index.forget(memory_id)

            assert index.count() == 0



    def test_persistence(self):

        from engram.layers.semantic_index import SemanticIndex

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:

            # Create and add

            index1 = SemanticIndex(persist_dir=tmpdir)

            index1.remember("Persistent memory test")

            del index1



            # Reopen and verify

            index2 = SemanticIndex(persist_dir=tmpdir)

            assert index2.count() == 1



    def test_batch_remember(self):

        from engram.layers.semantic_index import SemanticIndex

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:

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

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:

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

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:

            engram = Engram(persist_dir=tmpdir, auto_bootstrap=False)



            engram.remember("Jeremy prefers dark mode", category="user_preference", importance=0.9)

            engram.remember("Buckets app runs on port 5174", category="environment")



            recall = engram.recall("dashboard theme preference")

            assert len(recall.semantic_hits) > 0



    def test_hot_cache(self):

        from engram import Engram

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:

            engram = Engram(persist_dir=tmpdir, auto_bootstrap=False)



            engram.remember("Current task: refactoring dashboard", layer=1)

            engram.remember("Active branch: feat/react-refactor", layer=1)



            recall = engram.recall("dashboard refactor", layers=[1])

            assert len(recall.hot_cache) > 0



    def test_format_for_prompt(self):

        from engram import Engram

        from engram.utils.token_budget import TokenBudget

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:

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

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:

            engram = Engram(persist_dir=tmpdir, auto_bootstrap=False)

            engram.remember("test memory")

            stats = engram.stats()

            assert "semantic_index" in stats

            assert stats["semantic_index"]["total_memories"] == 1





if __name__ == "__main__":

    pytest.main([__file__, "-v", "--tb=short"])



class TestPromotionThresholds:

    """Phase 1: Promotion threshold boundary-condition tests."""



    def test_no_promotion_below_l3_threshold(self):

        """Memory at exactly min_recalls-1/min_importance does NOT promote."""

        from engram import Engram

        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:

            engram = Engram(persist_dir=tmpdir, auto_bootstrap=False)

            mem_id = engram.remember("Test skill pattern", category="skill", importance=0.40)

            # Manually set access_count to 1 (below L3_MIN_RECALLS=2)

            engram._semantic.collection.update(

                ids=[mem_id],

                metadatas=[{"category": "skill", "importance": 0.40, "access_count": 1}]

            )

            meta = engram._semantic.collection.get(ids=[mem_id], include=["metadatas"])

            engram._promote_memory(mem_id, meta["metadatas"][0], 0.40, 1)

            # Check category unchanged

            updated = engram._semantic.collection.get(ids=[mem_id], include=["metadatas"])

            assert updated["metadatas"][0]["category"] == "skill", (
                f"Should not promote at 1 recall, got {updated['metadatas'][0]['category']}"
            )



    def test_promotion_at_l3_boundary(self):

        """Memory at exactly min_recalls/min_importance DOES promote to L3 prefix."""

        from engram import Engram

        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:

            engram = Engram(persist_dir=tmpdir, auto_bootstrap=False)

            mem_id = engram.remember("Test workflow", category="skill", importance=0.40)

            engram._semantic.collection.update(

                ids=[mem_id],

                metadatas=[{"category": "skill", "importance": 0.40, "access_count": 2}]

            )

            meta = engram._semantic.collection.get(ids=[mem_id], include=["metadatas"])

            engram._promote_memory(mem_id, meta["metadatas"][0], 0.40, 2)

            updated = engram._semantic.collection.get(ids=[mem_id], include=["metadatas"])

            assert updated["metadatas"][0]["category"].startswith("L3_"), (
                f"Should promote to L3, got {updated['metadatas'][0]['category']}"
            )



    def test_no_double_promotion_skip_tier(self):

        """Memory with L3_ prefix is NOT re-promoted (skip guard works)."""

        from engram import Engram

        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:

            engram = Engram(persist_dir=tmpdir, auto_bootstrap=False)

            mem_id = engram.remember("Already promoted", category="L3_procedural_skill", importance=0.70)

            engram._semantic.collection.update(

                ids=[mem_id],

                metadatas=[{"category": "L3_procedural_skill", "importance": 0.70, "access_count": 8}]

            )

            meta = engram._semantic.collection.get(ids=[mem_id], include=["metadatas"])

            engram._promote_memory(mem_id, meta["metadatas"][0], 0.70, 8)

            updated = engram._semantic.collection.get(ids=[mem_id], include=["metadatas"])

            assert updated["metadatas"][0]["category"] == "L3_procedural_skill", (
                "Should not double-promote or skip L4"
            )



    def test_high_importance_boost_to_l3(self):

        """Memory with importance >= 0.8 and access_count < 2 gets free L3 promotion."""

        from engram import Engram

        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:

            engram = Engram(persist_dir=tmpdir, auto_bootstrap=False)

            mem_id = engram.remember("Critical insight", category="lesson_learned", importance=0.85)

            engram._semantic.collection.update(

                ids=[mem_id],

                metadatas=[{"category": "lesson_learned", "importance": 0.85, "access_count": 0}]

            )

            meta = engram._semantic.collection.get(ids=[mem_id], include=["metadatas"])

            engram._promote_memory(mem_id, meta["metadatas"][0], 0.85, 0)

            updated = engram._semantic.collection.get(ids=[mem_id], include=["metadatas"])

            assert updated["metadatas"][0]["category"].startswith("L3_"), (
                f"High importance should boost to L3, got {updated['metadatas'][0]['category']}"
            )



    def test_promotion_tiers_direct_from_l2(self):

        """Promotion jumps directly from L2 to the tier matching access_count."""

        from engram import Engram

        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:

            engram = Engram(persist_dir=tmpdir, auto_bootstrap=False)

            

            # L3: 2 recalls at 0.70 importance -> L3

            id3 = engram.remember("Pattern L3", category="skill", importance=0.70)

            engram._semantic.collection.update(

                ids=[id3], metadatas=[{"category": "skill", "importance": 0.70, "access_count": 2}]

            )

            meta3 = engram._semantic.collection.get(ids=[id3], include=["metadatas"])

            engram._promote_memory(id3, meta3["metadatas"][0], 0.70, 2)

            cat3 = engram._semantic.collection.get(ids=[id3], include=["metadatas"])["metadatas"][0]["category"]

            assert cat3.startswith("L3_"), f"2 recalls -> L3, got {cat3}"

            

            # L4: 4 recalls -> skips L3, goes directly L4

            id4 = engram.remember("Pattern L4", category="skill", importance=0.70)

            engram._semantic.collection.update(

                ids=[id4], metadatas=[{"category": "skill", "importance": 0.70, "access_count": 4}]

            )

            meta4 = engram._semantic.collection.get(ids=[id4], include=["metadatas"])

            engram._promote_memory(id4, meta4["metadatas"][0], 0.70, 4)

            cat4 = engram._semantic.collection.get(ids=[id4], include=["metadatas"])["metadatas"][0]["category"]

            assert cat4.startswith("L4_"), f"4 recalls -> L4, got {cat4}"

            

            # L5: 8 recalls -> directly L5

            id5 = engram.remember("Pattern L5", category="skill", importance=0.70)

            engram._semantic.collection.update(

                ids=[id5], metadatas=[{"category": "skill", "importance": 0.70, "access_count": 8}]

            )

            meta5 = engram._semantic.collection.get(ids=[id5], include=["metadatas"])

            engram._promote_memory(id5, meta5["metadatas"][0], 0.70, 8)

            cat5 = engram._semantic.collection.get(ids=[id5], include=["metadatas"])["metadatas"][0]["category"]

            assert cat5.startswith("L5_"), f"8 recalls -> L5, got {cat5}"



class TestDecayAndPurge:

    """Phase 6: Consolidation decay and purge paths."""



    def test_decay_reduces_old_memory_importance(self):

        """Memory past DECAY_DAYS with low access_count has importance reduced."""

        from engram import Engram

        from datetime import datetime, timedelta

        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:

            engram = Engram(persist_dir=tmpdir, auto_bootstrap=False)

            old_date = (datetime.now() - timedelta(days=40)).isoformat()

            mem_id = engram.remember("Old rarely-used fact", category="general", importance=0.5)

            engram._semantic.collection.update(

                ids=[mem_id],

                metadatas=[{

                    "category": "general", "importance": 0.5,

                    "access_count": 0, "created_at": old_date,

                }],

            )

            # Run consolidation tick directly

            engram._run_consolidation_tick()

            meta = engram._semantic.collection.get(ids=[mem_id], include=["metadatas"])["metadatas"]

            new_imp = meta[0]["importance"] if meta else 0.5

            assert new_imp < 0.5, f"Importance should decay: was 0.5, now {new_imp}"



    def test_purge_removes_below_min_importance(self):

        """Memory below _MIN_IMPORTANCE after decay is purged."""

        from engram import Engram

        from datetime import datetime, timedelta

        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:

            engram = Engram(persist_dir=tmpdir, auto_bootstrap=False)

            # Very old, very low importance — should be purged

            old_date = (datetime.now() - timedelta(days=365)).isoformat()

            mem_id = engram.remember("Very old trivia", category="general", importance=0.06)

            engram._semantic.collection.update(

                ids=[mem_id],

                metadatas=[{

                    "category": "general", "importance": 0.06,

                    "access_count": 0, "created_at": old_date,

                }],

            )

            count_before = engram._semantic.count()

            engram._run_consolidation_tick()

            count_after = engram._semantic.count()

            assert count_after < count_before, (
                f"Should purge: before={count_before}, after={count_after}"
            )


class TestRememberCollapsed:
    """Phase 8.1: remember() is a thin wrapper around remember_with_info()."""

    def test_remember_dedup_increments_counter(self):
        """Calling remember() on near-duplicate content increments _dedup_merged_count."""
        from engram import Engram
        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            engram = Engram(persist_dir=tmpdir, auto_bootstrap=False)

            # First store
            id1 = engram.remember("Jeremy prefers dark mode on all dashboards")
            assert engram._dedup_merged_count == 0

            # Same content again — should merge via remember(), which delegates to remember_with_info()
            id2 = engram.remember("Jeremy prefers dark mode on all dashboards")
            assert engram._dedup_merged_count == 1, (
                f"remember() should increment dedup counter via remember_with_info(). "
                f"Got {engram._dedup_merged_count}"
            )
            # Both return the same memory_id
            assert id1 == id2

    def test_remember_matches_remember_with_info(self):
        """remember()'s return must match remember_with_info()['memory_id'] for
        both new-stored and merged-duplicate cases."""
        from engram import Engram
        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            engram = Engram(persist_dir=tmpdir, auto_bootstrap=False)

            # Case 1: new memory — call remember_with_info first, then remember
            rwi = engram.remember_with_info("Unique fact A", category="test")
            assert rwi["merged"] is False

            rid = engram.remember("Unique fact A", category="test")
            # remember() delegates to remember_with_info which finds the duplicate
            assert rid == rwi["memory_id"], (
                f"remember() should return same ID after merge: {rid} vs {rwi['memory_id']}"
            )

            # Case 2: truly new content — both methods produce same ID
            rid2 = engram.remember("Unique fact B", category="test")
            rwi2 = engram.remember_with_info("Unique fact B", category="test")
            assert rid2 == rwi2["memory_id"], (
                f"Both should return same ID for duplicate: {rid2} vs {rwi2['memory_id']}"
            )
            assert rwi2["merged"] is True, (
                "Second store of same content should be a merge"
            )

