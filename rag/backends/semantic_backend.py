"""Semantic vector retrieval backend (v0.7 C2)."""

from __future__ import annotations

import logging

import config.settings as settings
from index.protocol import RetrievalHit
from rag.query import semantic_search
from rag.store import RagDisabledError

logger = logging.getLogger(__name__)


class SemanticBackend:
    name = "semantic"

    def search(
        self,
        query: str,
        *,
        repo_key: str,
        limit: int,
        path: str = "",
        extensions: str = "",
    ) -> list[RetrievalHit]:
        del repo_key, path, extensions

        if not settings.RAG_ENABLED:
            return []

        try:
            rag_hits = semantic_search(
                query,
                limit=limit,
                auto_build=True,
            )
        except RagDisabledError:
            return []
        except Exception as e:
            logger.warning("语义检索失败: %s", e, exc_info=True)
            return []

        hits: list[RetrievalHit] = []

        for item in rag_hits:
            scaled = min(0.7, max(0.0, item.score * 0.65))
            hits.append(
                RetrievalHit(
                    path=item.path,
                    line=item.start_line,
                    score=scaled,
                    snippet=item.snippet,
                    backend="semantic",
                    symbol_name=item.symbol_name,
                )
            )

        return hits
