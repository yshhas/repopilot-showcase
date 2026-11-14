"""Semantic context expansion for propose path (v0.7 C3)."""

from __future__ import annotations

import hashlib
import logging

import config.settings as settings
from index.protocol import RetrievalHit
from rag.query import semantic_search
from rag.store import RagDisabledError

logger = logging.getLogger(__name__)


def expand_semantic_candidates(task: str) -> list[RetrievalHit]:
    if not settings.RAG_ENABLED or not settings.RAG_CONTEXT_EXPAND:
        return []

    text = str(task or "").strip()
    if not text:
        return []

    try:
        hits = semantic_search(
            text,
            limit=settings.RAG_SEMANTIC_TOP_K,
            auto_build=True,
        )
    except RagDisabledError:
        return []
    except Exception as e:
        logger.warning("语义上下文扩展失败: %s", e, exc_info=True)
        return []

    return [
        RetrievalHit(
            path=item.path,
            line=item.start_line,
            score=item.score,
            snippet="",
            backend="semantic",
            symbol_name=item.symbol_name,
        )
        for item in hits
    ]


def task_query_hash(task: str) -> str:
    return hashlib.sha256(str(task or "").encode("utf-8")).hexdigest()[:16]
