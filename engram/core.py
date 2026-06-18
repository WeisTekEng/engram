
"""Engram core — the main memory orchestrator.

Ties together all 5 layers with token-aware retrieval.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import os

from .layers.semantic_index import SemanticIndex, Memory, SearchResult
from .utils.embedding import EmbeddingModel
from .utils.token_budget import TokenBudget


@dataclass
class RecallResult:
    """Aggregated recall across all layers."""
    hot_cache: List[str] = field(default_factory=list)
    semantic_hits: List[SearchResult] = field(default_factory=list)
    procedural_matches: List[str] = field(default_factory=list)
    episodic_matches: List[str] = field(default_factory=list)

    @property
    def all_memories(self) -> List[str]:
        """All memory content as strings, ordered by priority."""
        results = []
        results.extend(self.hot_cache)
        for hit in self.semantic_hits:
            results.append(hit.memory.content)
        results.extend(self.procedural_matches)
        results.extend(self.episodic_matches)
        return results

    def format_for_prompt(self, budget: TokenBudget) -> str:
        """Format memories for injection into the system prompt, respecting budget."""
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

        # Layer 2: Semantic Index
        if self.semantic_hits:
            lines = []
            for hit in self.semantic_hits:
                content = hit.memory.content
                if budget.consume(2, len(content)):
                    lines.append(f"- [{hit.score:.2f}] {content} ({hit.memory.category})")
            if lines:
                sections.append("## Relevant Memories\n" + "\n".join(lines))

        # Layer 3: Procedural (placeholder — will use skills)
        if self.procedural_matches:
            lines = []
            for item in self.procedural_matches:
                if budget.consume(3, len(item)):
                    lines.append(f"- {item}")
            if lines:
                sections.append("## Relevant Skills\n" + "\n".join(lines))

        # Layer 4: Episodic (placeholder)
        if self.episodic_matches:
            lines = []
            for item in self.episodic_matches:
                if budget.consume(4, len(item)):
                    lines.append(f"- {item}")
            if lines:
                sections.append("## Past Conversations\n" + "\n".join(lines))

        return "\n\n".join(sections) if sections else ""


class Engram:
    """Multi-layered memory system for Hermes AI agents.

    Usage:
        engram = Engram(persist_dir="~/.hermes/engram")
        engram.remember("Jeremy prefers dark mode", category="user_preference")
        recall = engram.recall("Change dashboard theme")
        prompt_context = recall.format_for_prompt(budget)
    """

    def __init__(
        self,
        persist_dir: str = "~/.hermes/engram",
        embedding_model: Optional[EmbeddingModel] = None,
        budget_max_chars: int = 2000,
        auto_bootstrap: bool = True,
    ):
        self.persist_dir = os.path.expanduser(persist_dir)
        self.embedding_model = embedding_model or EmbeddingModel()
        self.budget_max_chars = budget_max_chars

        # Initialize layers
        self._semantic = SemanticIndex(
            persist_dir=os.path.join(self.persist_dir, "semantic_index"),
            embedding_model=self.embedding_model,
        )

        # Layer 1: Hot Cache (in-memory, not persisted)
        self._hot_cache: List[str] = []

        # Bootstrap from existing Hermes memory if available
        if auto_bootstrap and self._semantic.count() == 0:
            self._bootstrap_from_hermes()

    def _bootstrap_from_hermes(self) -> None:
        """Import memories from Hermes's existing memory system."""
        import os

        # Check common Hermes memory file locations
        hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
        memory_files = []

        # Try multiple possible paths
        for path in [
            os.path.join(hermes_home, "memory", "memory.md"),
            os.path.join(hermes_home, "memory", "MEMORY.md"),
            os.path.join(hermes_home, "MEMORY.md"),
        ]:
            if os.path.exists(path):
                memory_files.append(path)

        for path in memory_files:
            try:
                self._import_markdown_memories(path)
            except Exception:
                pass

    def _import_markdown_memories(self, path: str) -> int:
        """Import memories from a markdown file. Returns count imported."""
        if not os.path.exists(path):
            return 0

        with open(path, "r") as f:
            content = f.read()

        # Split on section markers (###, ##, or blank lines between paragraphs)
        imported = 0
        current_section = "general"
        current_text = []

        for line in content.split("\n"):
            line = line.strip()
            if not line:
                if current_text:
                    text = " ".join(current_text)
                    if len(text) > 10:  # Skip very short fragments
                        self._semantic.remember(
                            text, category=current_section, importance=0.7
                        )
                        imported += 1
                    current_text = []
            elif line.startswith("### ") or line.startswith("## "):
                if current_text:
                    text = " ".join(current_text)
                    if len(text) > 10:
                        self._semantic.remember(
                            text, category=current_section, importance=0.7
                        )
                        imported += 1
                    current_text = []
                current_section = line.lstrip("# ").strip().lower().replace(" ", "_")
            else:
                current_text.append(line)

        # Don't forget the last section
        if current_text:
            text = " ".join(current_text)
            if len(text) > 10:
                self._semantic.remember(
                    text, category=current_section, importance=0.7
                )
                imported += 1

        return imported

    def remember(
        self,
        content: str,
        layer: int = 2,
        category: str = "general",
        importance: float = 0.5,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store a memory.

        Args:
            content: The memory text.
            layer: Which layer to store in (1-5). Default: 2 (Semantic Index).
            category: Memory type.
            importance: 0.0-1.0 priority.
            metadata: Extra key-value data.

        Returns:
            memory_id or "hot_cache" for Layer 1.
        """
        if layer == 1:
            self._hot_cache.append(content)
            # Keep hot cache pruned
            if len(self._hot_cache) > 20:
                self._hot_cache = self._hot_cache[-15:]
            return "hot_cache"
        elif layer == 2:
            return self._semantic.remember(content, category, importance, metadata)
        else:
            # Layers 3-5: forward to semantic index for now
            return self._semantic.remember(
                content, category=f"L{layer}_{category}", importance=importance,
                metadata=metadata
            )

    def recall(
        self,
        query: str,
        layers: Optional[List[int]] = None,
        limit: int = 10,
        min_score: float = 0.3,
    ) -> RecallResult:
        """Retrieve memories relevant to the query across layers.

        Args:
            query: The search query (user's message or task context).
            layers: Which layers to query. Default: [1, 2].
            limit: Max results per layer.
            min_score: Minimum relevance threshold.

        Returns:
            RecallResult with all matching memories.
        """
        if layers is None:
            layers = [1, 2]

        result = RecallResult()

        if 1 in layers:
            result.hot_cache = list(self._hot_cache[-5:])  # Last 5 hot cache items

        if 2 in layers:
            result.semantic_hits = self._semantic.recall(
                query, limit=limit, min_score=min_score
            )

        return result

    def forget(self, memory_id: str) -> bool:
        """Delete a memory. Returns True if successful."""
        if memory_id == "hot_cache":
            self._hot_cache.clear()
            return True
        return self._semantic.forget(memory_id)

    def budget_report(self) -> dict:
        """Get token budget utilization report."""
        budget = TokenBudget(max_chars=self.budget_max_chars)
        return budget.report()

    def stats(self) -> Dict[str, Any]:
        """Overall Engram statistics."""
        return {
            "semantic_index": self._semantic.stats(),
            "hot_cache_size": len(self._hot_cache),
            "budget_max_chars": self.budget_max_chars,
            "persist_dir": self.persist_dir,
        }

    def close(self) -> None:
        """Release all resources (ChromaDB clients, file locks)."""
        self._semantic.close()

    def clear(self) -> None:
        """Clear all memory layers. Irreversible!"""
        self._semantic.clear()
        self._hot_cache.clear()
