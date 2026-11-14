"""Embedding providers for repo RAG (v0.7 C1)."""

from __future__ import annotations

import hashlib
import math
from typing import Protocol

import config.settings as settings


class EmbeddingProvider(Protocol):
    model_name: str
    embedding_dim: int

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, query: str) -> list[float]:
        ...


def _normalize_vector(values: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in values))
    if magnitude <= 0:
        return values
    return [value / magnitude for value in values]


class MockEmbeddingProvider:
    """Deterministic local embeddings for CI (no network)."""

    model_name = "mock-deterministic-v1"

    def __init__(self, embedding_dim: int | None = None):
        self.embedding_dim = embedding_dim or settings.RAG_EMBEDDING_DIM

    def _vector_for_text(self, text: str) -> list[float]:
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        values: list[float] = []

        for index in range(self.embedding_dim):
            byte_a = seed[index % len(seed)]
            byte_b = seed[(index + 7) % len(seed)]
            values.append((byte_a / 255.0) * 2.0 - 1.0 + (byte_b / 255.0) * 0.01)

        return _normalize_vector(values)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._vector_for_text(text) for text in texts]

    def embed_query(self, query: str) -> list[float]:
        return self._vector_for_text(query)


class ChromaDefaultEmbeddingProvider:
    """Chroma built-in ONNX embedding model (optional runtime build)."""

    model_name = "chromadb-default"

    def __init__(self):
        from chromadb.utils import embedding_functions

        self._embedding_func = embedding_functions.DefaultEmbeddingFunction()
        probe = self._embedding_func(["probe"])[0]
        self.embedding_dim = len(probe)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self._embedding_func(texts)

    def embed_query(self, query: str) -> list[float]:
        return self._embedding_func([query])[0]


def get_embedding_provider(*, force_mock: bool = False) -> EmbeddingProvider:
    if force_mock or settings.RAG_EMBEDDING_MODEL == MockEmbeddingProvider.model_name:
        return MockEmbeddingProvider()

    return ChromaDefaultEmbeddingProvider()
