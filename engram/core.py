

"""Engram core — the main memory orchestrator.

Ties together all 5 layers with token-aware retrieval,
auto-consolidation, dedup, and L1 persistence.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Callable
import json
import os
import threading
import time
from datetime import datetime, timedelta

from .layers.semantic_index import SemanticIndex, Memory, SearchResult
from .utils.embedding import EmbeddingModel
from .utils.token_budget import TokenBudget


# ── Constants ──────────────────────────────────────────────────────

_HOT_CACHE_MAX = 30          # max items in L1 before pruning
_HOT_CACHE_KEEP = 20         # items kept after pruning
_HOT_CACHE_RETURN = 15       # items returned on recall
_CONSOLIDATION_INTERVAL = 1800  # 30 minutes between consolidation ticks
_DEDUP_THRESHOLD = 0.85      # semantic similarity for merge-on-write
_DECAY_DAYS = 30             # after N days without access, start decaying
_MIN_IMPORTANCE = 0.05       # floor before auto-purge
_L1_PERSIST_FILE = "l1_hot_cache.json"

# Layer promotion thresholds (canonical — the single source of truth)
_L3_MIN_RECALLS = 2          # L2→L3: procedural
_L3_MIN_IMPORTANCE = 0.40
_L4_MIN_RECALLS = 4          # L3→L4: episodic
_L4_MIN_IMPORTANCE = 0.55
_L5_MIN_RECALLS = 8          # L4→L5: reflection
_L5_MIN_IMPORTANCE = 0.70
_HIGH_IMPORTANCE_BOOST = 0.8 # free promotion to L3 at this importance


@dataclass
class RecallResult:
    """Aggregated recall across all layers."""
    hot_cache: List[str] = field(default_factory=list)
    semantic_hits: List[SearchResult] = field(default_factory=list)
    procedural_matches: List[str] = field(default_factory=list)
    episodic_matches: List[str] = field(default_factory=list)
    reflection_matches: List[str] = field(default_factory=list)
    unified: List[dict] = field(default_factory=list)  # cross-layer ranked list

    @property
    def all_memories(self) -> List[str]:
        """All memory content as strings, ordered by priority."""
        results = list(self.hot_cache)
        for hit in self.semantic_hits:
            results.append(hit.memory.content)
        results.extend(self.procedural_matches)
        results.extend(self.episodic_matches)
        results.extend(self.reflection_matches)
        return results

    def format_for_prompt(self, budget: TokenBudget) -> str:
        """Format memories for the system prompt, respecting token budget."""
        budget.allocate()
        sections = []

        # Layer 1: Hot Cache
        if self.hot_cache:
            chars = 0
            lines = []
            for item in self.hot_cache:
                if chars + len(item) <= budget.allocations[0].remaining:
                    budget.consume(1, len(item))
                    lines.append(f"- {item}")
                    chars += len(item)
            if lines:
                sections.append("## Active Context\n" + "\n".join(lines))

        # Layers 2-5: Ranked unified list
        if self.unified:
            lines = []
            for item in self.unified:
                content = item.get("content", "")
                score = item.get("score", 0)
                layer_name = item.get("layer", "")
                label = f"[{score:.2f}] {content}" + (f" ({layer_name})" if layer_name else "")
                if budget.consume(2, len(label)):
                    lines.append(f"- {label}")
            if lines:
                sections.append("## Relevant Memories\n" + "\n".join(lines))

        return "\n\n".join(sections) if sections else ""


class Engram:
    """Multi-layered memory system with auto-consolidation and dedup.

    Features:
      - Dedup-on-write: semantically similar content merges instead of duplicates
      - Auto-consolidation: background thread decays old memories, purges cruft
      - L1 persistence: hot cache saves/loads on shutdown/startup
      - Unified recall: one query searches all 5 layers
      - Session-aware L1: recent topics stay hot
    """

    def __init__(
        self,
        persist_dir: str = "~/.hermes/engram",
        embedding_model: Optional[EmbeddingModel] = None,
        budget_max_chars: int = 2000,
        auto_bootstrap: bool = True,
        enable_consolidation: bool = True,
    ):
        self.persist_dir = os.path.expanduser(persist_dir)
        self.embedding_model = embedding_model or EmbeddingModel()
        self.budget_max_chars = budget_max_chars

        # Initialize layers
        self._semantic = SemanticIndex(
            persist_dir=os.path.join(self.persist_dir, "semantic_index"),
            embedding_model=self.embedding_model,
        )

        # Layer 1: Hot Cache (in-memory, now persisted)
        self._hot_cache: List[str] = []
        self._load_l1()  # restore from disk if available

        # Session tracking for L1 awareness
        self._session_topic: str = ""
        self._session_keywords: List[str] = []

        # Bootstrap from existing Hermes memory if available
        if auto_bootstrap and self._semantic.count() == 0:
            self._bootstrap_from_hermes()

        # Background consolidation thread (daemon — auto-shutdown)
        self._consolidation_enabled = enable_consolidation
        self._consolidation_stop = threading.Event()
        self._consolidation_thread: Optional[threading.Thread] = None
        if enable_consolidation:
            self._start_consolidation()

    # ── L1 Persistence ─────────────────────────────────────────────

    def _l1_path(self) -> str:
        return os.path.join(self.persist_dir, _L1_PERSIST_FILE)

    def _save_l1(self) -> None:
        """Dump hot cache to disk."""
        try:
            path = self._l1_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(self._hot_cache, f)
        except Exception:
            pass

    def _load_l1(self) -> None:
        """Restore hot cache from disk."""
        try:
            path = self._l1_path()
            if os.path.exists(path):
                with open(path) as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self._hot_cache = data[-_HOT_CACHE_MAX:]
        except Exception:
            self._hot_cache = []

    # ── Dedup-on-Write ─────────────────────────────────────────────

    def _find_duplicate(self, content: str) -> Optional[SearchResult]:
        """Check if semantically similar content already exists."""
        results = self._semantic.recall(
            query=content,
            limit=1,
            min_score=_DEDUP_THRESHOLD,
        )
        return results[0] if results else None

    def _push_hot(self, content: str) -> None:
        """Push into L1, pruning at capacity. Skips duplicates."""
        if content in self._hot_cache:
            # Move to end (MRU position) instead of duplicating
            self._hot_cache.remove(content)
        self._hot_cache.append(content)
        if len(self._hot_cache) > _HOT_CACHE_MAX:
            self._hot_cache = self._hot_cache[-_HOT_CACHE_KEEP:]

    def remember(
        self,
        content: str,
        layer: int = 2,
        category: str = "general",
        importance: float = 0.5,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store a memory with automatic dedup and L1 warmup.

        If semantically similar content exists (score >= {_DEDUP_THRESHOLD}),
        the existing entry's importance is boosted and the new store is
        skipped — no duplicate created.
        """
        # Always push to L1
        self._push_hot(content)

        # Dedup check: if similar content exists, merge importance instead
        dup = self._find_duplicate(content)
        if dup:
            existing = dup.memory
            new_importance = max(existing.importance, importance)
            new_importance = min(1.0, new_importance + 0.05)  # small boost
            self._semantic.update_importance(existing.id, new_importance)
            return existing.id  # return the existing ID

        if layer == 1:
            return "hot_cache"
        elif layer == 2:
            return self._semantic.remember(content, category, importance, metadata)
        else:
            return self._semantic.remember(
                content, category=f"L{layer}_{category}", importance=importance,
                metadata=metadata
            )

    # ── Unified Recall ─────────────────────────────────────────────

    def recall(
        self,
        query: str,
        layers: Optional[List[int]] = None,
        limit: int = 10,
        min_score: float = 0.3,
    ) -> RecallResult:
        """Retrieve memories across all requested layers with unified ranking.

        When layers is None, ALL layers (1-5) are queried and results are
        merged into a single ranked list in ``unified``.  The per-layer
        buckets (hot_cache, semantic_hits, etc.) are still populated for
        backwards compat.
        """
        if layers is None:
            layers = [1, 2, 3, 4, 5]

        result = RecallResult()

        # Helper to map a category string to a bucketed list on result
        _CAT_BUCKETS = {
            "L3_": "procedural_matches",
            "L4_": "episodic_matches",
            "L5_": "reflection_matches",
        }

        # Layer 1: Hot Cache — filter by query relevance (word overlap)
        if 1 in layers:
            query_lower = query.lower()
            query_words = set(query_lower.split())
            all_hot = list(self._hot_cache[-_HOT_CACHE_RETURN:])
            result.hot_cache = [
                h for h in all_hot
                if any(w in h.lower() for w in query_words if len(w) > 2)
            ] if query_words else all_hot

        # Layers 2-5: Query ChromaDB, then bucket + unify
        if any(l in layers for l in (2, 3, 4, 5)):
            # Get a generous pool to cover all layers
            pool_limit = max(limit * 3, 30)
            all_hits = self._semantic.recall(query, limit=pool_limit, min_score=min_score)

            for hit in all_hits:
                cat = hit.memory.category

                if cat.startswith("L3_"):
                    getattr(result, _CAT_BUCKETS["L3_"]).append(hit.memory.content)
                    result.unified.append({
                        "content": hit.memory.content,
                        "score": hit.score,
                        "layer": "procedural",
                        "category": cat[3:],
                        "importance": hit.memory.importance,
                        "memory_id": hit.memory.id,
                        "metadata": hit.memory.metadata or {},
                    })
                elif cat.startswith("L4_"):
                    getattr(result, _CAT_BUCKETS["L4_"]).append(hit.memory.content)
                    result.unified.append({
                        "content": hit.memory.content,
                        "score": hit.score,
                        "layer": "episodic",
                        "category": cat[3:],
                        "importance": hit.memory.importance,
                        "memory_id": hit.memory.id,
                        "metadata": hit.memory.metadata or {},
                    })
                elif cat.startswith("L5_"):
                    getattr(result, _CAT_BUCKETS["L5_"]).append(hit.memory.content)
                    result.unified.append({
                        "content": hit.memory.content,
                        "score": hit.score,
                        "layer": "reflection",
                        "category": cat[3:],
                        "importance": hit.memory.importance,
                        "memory_id": hit.memory.id,
                        "metadata": hit.memory.metadata or {},
                    })
                else:
                    # Layer 2 (no prefix)
                    result.semantic_hits.append(hit)
                    result.unified.append({
                        "content": hit.memory.content,
                        "score": hit.score,
                        "layer": "memory (" + cat + ")",
                        "category": cat,
                        "importance": hit.memory.importance,
                        "memory_id": hit.memory.id,
                        "metadata": hit.memory.metadata or {},
                    })

            # Sort unified by combined score: semantic_score * 0.6 + importance * 0.4
            for item in result.unified:
                item["combined_score"] = (
                    item["score"] * 0.6 + item["importance"] * 0.4
                )
            result.unified.sort(key=lambda x: x["combined_score"], reverse=True)
            result.unified = result.unified[:limit]

            # Track access count for all hits in one batch (O(2) I/O instead of O(2N))
            if all_hits:
                self._semantic.batch_increment_access_count([h.memory.id for h in all_hits])

            # Warm L1 with the top hit
            if all_hits:
                self._push_hot(all_hits[0].memory.content)

        return result

    # ── Auto-Consolidation (background thread) ─────────────────────

    def _start_consolidation(self) -> None:
        self._consolidation_thread = threading.Thread(
            target=self._consolidation_loop,
            daemon=True,
            name="engram-consolidation",
        )
        self._consolidation_thread.start()

    def _consolidation_loop(self) -> None:
        """Background loop: decay old memories, merge near-duplicates, prune cruft."""
        while not self._consolidation_stop.is_set():
            # Wait for the interval (check stop every 5s for responsive shutdown)
            waited = 0
            while waited < _CONSOLIDATION_INTERVAL:
                if self._consolidation_stop.wait(5):
                    return  # stop signalled
                waited += 5

            try:
                self._run_consolidation_tick()
            except Exception:
                pass  # never let the loop die

    def _promote_memory(self, mem_id: str, meta: dict, importance: float, access_count: int) -> None:
        """Promote a memory to higher layers based on frequency and importance."""
        cat = meta.get("category", "general")
        # Don't re-promote already-promoted memories
        if cat.startswith("L3_") or cat.startswith("L4_") or cat.startswith("L5_"):
            return

        # High importance gate: anything >= threshold gets at least L3
        if importance >= _HIGH_IMPORTANCE_BOOST and access_count < _L3_MIN_RECALLS:
            access_count = _L3_MIN_RECALLS  # boost to L3 threshold

        if access_count >= _L5_MIN_RECALLS and importance >= _L5_MIN_IMPORTANCE:
            # Promote to L5 (reflection)
            new_cat = f"L5_reflection_{cat}"
            meta["importance"] = min(1.0, importance + 0.1)
        elif access_count >= _L4_MIN_RECALLS and importance >= _L4_MIN_IMPORTANCE:
            # Promote to L4 (episodic)
            new_cat = f"L4_episodic_{cat}"
            meta["importance"] = min(1.0, importance + 0.05)
        elif access_count >= _L3_MIN_RECALLS and importance >= _L3_MIN_IMPORTANCE:
            # Promote to L3 (procedural)
            new_cat = f"L3_procedural_{cat}"
        else:
            return  # Not eligible for promotion

        meta["category"] = new_cat
        try:
            self._semantic.collection.update(ids=[mem_id], metadatas=[meta])
        except Exception:
            pass

    def _run_consolidation_tick(self) -> None:
        """One tick of auto-consolidation. Decays old, purges cruft, promotes hot."""
        from .layers.semantic_index import Memory

        # Get ALL memories from ChromaDB
        all_data = self._semantic.collection.get(include=["metadatas", "documents"])
        if not all_data or not all_data["ids"]:
            return

        now = datetime.now()
        decayed = 0
        purged = 0

        for i, mem_id in enumerate(all_data["ids"]):
            meta = (all_data["metadatas"] or [{}])[i] or {}
            doc = (all_data["documents"] or [""])[i] or ""

            # Parse created_at
            created_str = meta.get("created_at", "")
            created = datetime.fromisoformat(created_str) if created_str else now
            age_days = (now - created).total_seconds() / 86400

            importance = float(meta.get("importance", 0.5))
            access_count = int(meta.get("access_count", 0))

            # Decay: after DECAY_DAYS, reduce importance
            if age_days > _DECAY_DAYS and access_count < 5:
                decay_factor = max(0.0, 1.0 - (age_days - _DECAY_DAYS) / 90.0)
                new_importance = importance * decay_factor
                if new_importance < _MIN_IMPORTANCE:
                    # Purge
                    try:
                        self._semantic.collection.delete(ids=[mem_id])
                        purged += 1
                    except Exception:
                        pass
                elif new_importance < importance - 0.02:
                    try:
                        self._semantic.collection.update(
                            ids=[mem_id],
                            metadatas=[{**meta, "importance": new_importance}],
                        )
                        decayed += 1
                    except Exception:
                        pass

            # Promotion check: frequently-recalled memories move up layers
            if age_days < 60:  # Only promote memories less than 60 days old
                self._promote_memory(mem_id, meta, importance, access_count)

    # ── Lifecycle ──────────────────────────────────────────────────

    def trigger_consolidation(self) -> dict:
        """Manually trigger a consolidation tick. Returns counts."""
        before = self._semantic.count()
        self._run_consolidation_tick()
        after = self._semantic.count()
        return {
            "status": "done",
            "before": before,
            "after": after,
            "purged": before - after,
            "note": "decay + prune run",
        }

    def forget(self, memory_id: str) -> bool:
        if memory_id == "hot_cache":
            self._hot_cache.clear()
            return True
        return self._semantic.forget(memory_id)

    def budget_report(self) -> dict:
        budget = TokenBudget(max_chars=self.budget_max_chars)
        return budget.report()

    def stats(self) -> Dict[str, Any]:
        s = self._semantic.stats()
        # Count memories per layer
        layer_counts = {"L1_hot": len(self._hot_cache), "L2_semantic": 0, "L3_procedural": 0, "L4_episodic": 0, "L5_reflection": 0}
        try:
            all_data = self._semantic.collection.get(include=["metadatas"])
            if all_data and all_data["metadatas"]:
                for m in all_data["metadatas"]:
                    cat = (m or {}).get("category", "")
                    if cat.startswith("L3_"): layer_counts["L3_procedural"] += 1
                    elif cat.startswith("L4_"): layer_counts["L4_episodic"] += 1
                    elif cat.startswith("L5_"): layer_counts["L5_reflection"] += 1
                    else: layer_counts["L2_semantic"] += 1
        except Exception:
            pass
        return {
            "semantic_index": s,
            "layers": layer_counts,
            "hot_cache_size": len(self._hot_cache),
            "budget_max_chars": self.budget_max_chars,
            "persist_dir": self.persist_dir,
            "consolidation": {
                "enabled": self._consolidation_enabled,
                "thread_alive": (
                    self._consolidation_thread is not None
                    and self._consolidation_thread.is_alive()
                ),
                "interval_seconds": _CONSOLIDATION_INTERVAL,
                "decay_days": _DECAY_DAYS,
            },
        }

    def close(self) -> None:
        """Graceful shutdown: stop consolidation, save L1, release resources."""
        # Stop consolidation thread
        if self._consolidation_enabled:
            self._consolidation_stop.set()
            if self._consolidation_thread and self._consolidation_thread.is_alive():
                self._consolidation_thread.join(timeout=3)

        # Persist L1 hot cache
        self._save_l1()

        # Release ChromaDB
        self._semantic.close()

    def clear(self) -> None:
        self._semantic.clear()
        self._hot_cache.clear()
