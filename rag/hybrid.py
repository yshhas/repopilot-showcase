"""Hybrid retrieval merge rank (v0.7 C2)."""

from __future__ import annotations

import config.settings as settings
from index.builder import compute_repo_key
from index.protocol import RetrievalBackend, RetrievalHit
from rag.backends.grep_backend import GrepBackend
from rag.backends.semantic_backend import SemanticBackend
from rag.backends.symbol_backend import SymbolBackend


class HybridRetriever:
    def __init__(self, backends: list[RetrievalBackend]):
        self.backends = list(backends)

    def merge_rank(
        self,
        query: str,
        *,
        repo_key: str | None = None,
        limit: int | None = None,
        path: str = "",
        extensions: str = "",
    ) -> list[RetrievalHit]:
        text = str(query or "").strip()
        if not text:
            return []

        key = repo_key or compute_repo_key()
        max_results = limit or settings.DEFAULT_SEARCH_MAX_RESULTS

        merged: dict[tuple[str, int], RetrievalHit] = {}

        for backend in self.backends:
            search_kwargs = {
                "query": text,
                "repo_key": key,
                "limit": max_results,
            }

            if isinstance(backend, GrepBackend):
                hits = backend.search(
                    **search_kwargs,
                    path=path,
                    extensions=extensions,
                )
            else:
                hits = backend.search(**search_kwargs)

            for hit in hits:
                bucket_key = (hit.path, hit.line)
                existing = merged.get(bucket_key)

                if existing is None:
                    merged[bucket_key] = hit
                    continue

                combined_score = existing.score + hit.score * 0.35
                winner = existing if existing.score >= hit.score else hit
                merged[bucket_key] = RetrievalHit(
                    path=winner.path,
                    line=winner.line,
                    score=combined_score,
                    snippet=winner.snippet or existing.snippet,
                    backend=winner.backend + "+" + hit.backend,
                    symbol_name=winner.symbol_name or hit.symbol_name,
                )

        ranked = sorted(
            merged.values(),
            key=lambda item: (-item.score, item.path, item.line),
        )
        return ranked[:max_results]


def create_default_hybrid_retriever() -> HybridRetriever:
    backends: list[RetrievalBackend] = [GrepBackend()]

    if settings.INDEX_ENABLED:
        backends.append(SymbolBackend())

    if settings.RAG_ENABLED:
        backends.append(SemanticBackend())

    return HybridRetriever(backends)


def format_hybrid_hits(hits: list[RetrievalHit]) -> list[str]:
    lines: list[str] = []

    for hit in hits:
        prefix = "[" + hit.backend + "] "
        score_text = " (score=" + format(hit.score, ".2f") + ")"
        lines.append(
            prefix
            + hit.path
            + ":"
            + str(hit.line)
            + score_text
            + ": "
            + hit.snippet
        )

    return lines
