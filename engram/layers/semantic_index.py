
"""Layer 2: Semantic Index — vector-backed relevance retrieval.

This is the biggest token-savings lever. Instead of dumping ALL memories
into every turn, we only inject memories whose embeddings are similar
to the current query.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
import hashlib
import uuid

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    HAS_CHROMA = True
except ImportError:
    HAS_CHROMA = False

from ..utils.embedding import EmbeddingModel


@dataclass
class Memory:
    """A single memory entry stored in the semantic index."""

    id: str
    content: str
    category: str  # e.g. "user_preference", "environment", "lesson_learned"
    importance: float = 0.5  # 0.0-1.0, used for ranking
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_accessed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    access_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def age_days(self) -> float:
        """How many days since this memory was created."""
        created = datetime.fromisoformat(self.created_at)
        return (datetime.now() - created).total_seconds() / 86400


@dataclass
class SearchResult:
    """A memory match with a relevance score."""

    memory: Memory
    score: float  # cosine similarity, 0.0-1.0


class SemanticIndex:
    """ChromaDB-backed vector store for Layer 2 memory.

    Stores memories as embeddings and retrieves them by semantic similarity.
    """

    def __init__(
        self,
        persist_dir: str = "~/.hermes/engram/semantic_index",
        embedding_model: Optional[EmbeddingModel] = None,
        collection_name: str = "engram_memories",
    ):
        import os
        self.persist_dir = os.path.expanduser(persist_dir)

        if not HAS_CHROMA:
            raise ImportError(
                "chromadb is required for SemanticIndex. "
                "Install with: pip install chromadb"
            )

        # Embedding model
        self.embedding_model = embedding_model or EmbeddingModel()

        # ChromaDB client (persistent)
        self.client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def __del__(self):
        """Attempt to close ChromaDB on deletion."""
        try:
            self.close()
        except Exception:
            pass

    def remember(
        self,
        content: str,
        category: str = "general",
        importance: float = 0.5,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store a memory and return its ID.

        Args:
            content: The memory text to store.
            category: Type of memory (user_preference, environment, etc.).
            importance: 0.0-1.0 priority score.
            metadata: Additional key-value metadata.

        Returns:
            memory_id: Unique identifier for the stored memory.
        """
        memory_id = hashlib.sha256(
            f"{category}:{content}:{datetime.now().isoformat()}".encode()
        ).hexdigest()[:16]

        # Generate embedding
        embedding = self.embedding_model.embed_single(content)

        # Store in ChromaDB
        self.collection.add(
            ids=[memory_id],
            embeddings=[embedding.vector.tolist()],
            documents=[content],
            metadatas=[{
                "category": category,
                "importance": importance,
                "created_at": datetime.now().isoformat(),
                "content_hash": hashlib.md5(content.encode()).hexdigest(),
                **(metadata or {}),
            }],
        )

        return memory_id

    def recall(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.3,
        category_filter: Optional[str] = None,
    ) -> List[SearchResult]:
        """Retrieve memories semantically similar to the query.

        Args:
            query: The search query (typically the user's message).
            limit: Maximum number of results.
            min_score: Minimum cosine similarity threshold.
            category_filter: Optional category to filter by.

        Returns:
            List of SearchResult sorted by relevance.
        """
        # Generate query embedding
        query_embedding = self.embedding_model.embed_single(query)

        # Build filter
        where_filter = None
        if category_filter:
            where_filter = {"category": category_filter}

        # Query ChromaDB
        results = self.collection.query(
            query_embeddings=[query_embedding.vector.tolist()],
            n_results=limit,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        # Map to SearchResult objects
        search_results = []
        if results["ids"] and results["ids"][0]:
            for i, mem_id in enumerate(results["ids"][0]):
                distance = results["distances"][0][i] if results["distances"] else 1.0
                # ChromaDB with cosine returns distance (0=identical, 2=opposite)
                # Convert to similarity score (1=identical, 0=opposite)
                score = 1.0 - (distance / 2.0)

                if score >= min_score:
                    doc = results["documents"][0][i] if results["documents"] else ""
                    meta = results["metadatas"][0][i] if results["metadatas"] else {}

                    memory = Memory(
                        id=mem_id,
                        content=doc,
                        category=meta.get("category", "general"),
                        importance=float(meta.get("importance", 0.5)),
                        created_at=meta.get("created_at", datetime.now().isoformat()),
                        metadata=meta,
                    )
                    search_results.append(SearchResult(memory=memory, score=score))

        return search_results

    def forget(self, memory_id: str) -> bool:
        """Delete a memory by ID. Returns True if deleted."""
        try:
            self.collection.delete(ids=[memory_id])
            return True
        except Exception:
            return False

    def count(self) -> int:
        """Total number of stored memories."""
        return self.collection.count()

    def list_categories(self) -> List[str]:
        """List all unique categories in the index."""
        results = self.collection.get(include=["metadatas"])
        categories = set()
        if results["metadatas"]:
            for meta in results["metadatas"]:
                if meta and "category" in meta:
                    categories.add(meta["category"])
        return sorted(categories)

    def close(self) -> None:
        """Close the ChromaDB client, releasing file locks."""
        try:
            del self.collection
            del self.client
        except Exception:
            pass

    def clear(self) -> None:
        """Delete all memories. Irreversible!"""
        self.client.delete_collection(self.collection.name)
        self.collection = self.client.get_or_create_collection(
            name=self.collection.name,
            metadata={"hnsw:space": "cosine"},
        )

    def stats(self) -> Dict[str, Any]:
        """Get collection statistics."""
        return {
            "total_memories": self.count(),
            "categories": self.list_categories(),
            "persist_dir": self.persist_dir,
            "embedding_model": self.embedding_model.model_name,
            "embedding_dims": self.embedding_model.dimensions,
        }

    def batch_remember(
        self, memories: List[Dict[str, Any]]
    ) -> List[str]:
        """Store multiple memories efficiently in a single batch.

        Args:
            memories: List of dicts with keys: content, category, importance, metadata.

        Returns:
            List of memory IDs.
        """
        ids = []
        embeddings = []
        documents = []
        metadatas = []

        for mem in memories:
            content = mem["content"]
            category = mem.get("category", "general")
            importance = mem.get("importance", 0.5)
            metadata = mem.get("metadata", {})

            memory_id = hashlib.sha256(
                f"{category}:{content}:{datetime.now().isoformat()}".encode()
            ).hexdigest()[:16]
            ids.append(memory_id)

            emb = self.embedding_model.embed_single(content)
            embeddings.append(emb.vector.tolist())
            documents.append(content)
            metadatas.append({
                "category": category,
                "importance": importance,
                "created_at": datetime.now().isoformat(),
                "content_hash": hashlib.md5(content.encode()).hexdigest(),
                **metadata,
            })

        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

        return ids


# ---- Standalone test ----
if __name__ == "__main__":
    import tempfile, os

    with tempfile.TemporaryDirectory() as tmpdir:
        index = SemanticIndex(persist_dir=tmpdir)

        # Add some memories
        id1 = index.remember("Jeremy prefers dark mode on all dashboards", category="user_preference", importance=0.9)
        id2 = index.remember("The Buckets app runs on port 5174 via Tailscale", category="environment", importance=0.8)
        id3 = index.remember("Composer is the PHP package manager", category="general", importance=0.2)

        print(f"Stored {index.count()} memories")

        # Recall
        results = index.recall("What dashboard theme does Jeremy like?")
        for r in results:
            print(f"  [{r.score:.2f}] {r.memory.content}")

        # Search for something unrelated
        results = index.recall("How do I deploy a PHP app?")
        for r in results:
            print(f"  [{r.score:.2f}] {r.memory.content}")

        print("Stats:", index.stats())
        print("OK")
