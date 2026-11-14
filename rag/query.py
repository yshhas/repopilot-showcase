"""Semantic query API for repo RAG (v0.7 C1)."""

from __future__ import annotations

from pathlib import Path

import config.settings as settings
from index.builder import compute_repo_key
from rag.builder import build_rag_index, needs_rebuild
from rag.embedder import EmbeddingProvider, get_embedding_provider
from rag.models import RagHit, RagMeta
from rag.store import RagDisabledError, is_rag_enabled, load_rag_meta, query_similar


def get_rag_meta(repo_root: Path | None = None) -> RagMeta | None:
    if not is_rag_enabled():
        return None

    repo_key = compute_repo_key(repo_root)
    return load_rag_meta(repo_key)


def ensure_rag(repo_root: Path | None = None, *, force: bool = False) -> RagMeta | None:
    if not is_rag_enabled():
        return None

    root = repo_root or settings.REPO_ROOT

    if force or needs_rebuild(root):
        result = build_rag_index(root, force=force)
        if not result.ok:
            return None
        return result.meta

    return get_rag_meta(root)


def semantic_search(
    query: str,
    *,
    repo_root: Path | None = None,
    limit: int | None = None,
    auto_build: bool = True,
    embedding_provider: EmbeddingProvider | None = None,
) -> list[RagHit]:
    if not is_rag_enabled():
        raise RagDisabledError("Repo RAG is disabled (RAG_ENABLED=0)")

    text = str(query).strip()
    if not text:
        return []

    root = repo_root or settings.REPO_ROOT
    max_results = limit or settings.RAG_SEMANTIC_TOP_K

    if auto_build:
        ensure_rag(root)

    repo_key = compute_repo_key(root)
    meta = load_rag_meta(repo_key)
    if meta is None:
        return []

    provider = embedding_provider or get_embedding_provider(force_mock=True)
    if provider.embedding_dim != meta.embedding_dim:
        ensure_rag(root, force=True)
        meta = load_rag_meta(repo_key)
        if meta is None:
            return []

    query_embedding = provider.embed_query(text)
    return query_similar(repo_key, query_embedding, limit=max_results)
