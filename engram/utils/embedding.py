
"""Embedding model wrapper — pluggable backends, lazy loading."""

from dataclasses import dataclass
from typing import Optional, List
import numpy as np


@dataclass
class EmbeddingResult:
    """A single embedding vector with metadata."""
    text: str
    vector: np.ndarray
    model_name: str
    dimensions: int


class EmbeddingModel:
    """Lazy-loading wrapper around sentence-transformers or OpenAI embeddings.

    Default: all-MiniLM-L6-v2 (384 dims, fast, free, runs locally).
    Also supports OpenAI text-embedding-3-small via API key.
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        provider: str = "local",
        openai_api_key: Optional[str] = None,
    ):
        self.model_name = model_name
        self.provider = provider
        self.openai_api_key = openai_api_key
        self._model = None
        self._dimensions_cache: Optional[int] = None

    @property
    def model(self):
        if self._model is None:
            self._model = self._load_model()
        return self._model

    def _load_model(self):
        if self.provider == "local":
            from sentence_transformers import SentenceTransformer
            return SentenceTransformer(self.model_name)
        elif self.provider == "openai":
            # Deferred import — only if user has openai installed
            from openai import OpenAI
            return OpenAI(api_key=self.openai_api_key)
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

    def embed(self, texts: List[str]) -> List[EmbeddingResult]:
        """Embed one or more texts. Returns list of EmbeddingResult."""
        if self.provider == "local":
            vectors = self.model.encode(texts, convert_to_numpy=True)
            if vectors.ndim == 1:
                vectors = vectors.reshape(1, -1)
            return [
                EmbeddingResult(
                    text=text,
                    vector=vectors[i],
                    model_name=self.model_name,
                    dimensions=vectors.shape[1],
                )
                for i, text in enumerate(texts)
            ]
        elif self.provider == "openai":
            response = self.model.embeddings.create(
                input=texts, model=self.model_name
            )
            return [
                EmbeddingResult(
                    text=texts[i],
                    vector=np.array(d.embedding),
                    model_name=self.model_name,
                    dimensions=len(d.embedding),
                )
                for i, d in enumerate(response.data)
            ]

    def embed_single(self, text: str) -> EmbeddingResult:
        """Embed a single text. Convenience wrapper."""
        return self.embed([text])[0]

    @property
    def dimensions(self) -> int:
        """Get embedding dimensions (cached after first access)."""
        if self._dimensions_cache is None:
            self._dimensions_cache = self.embed_single("test").dimensions
        return self._dimensions_cache
