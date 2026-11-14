"""Repo RAG package (v0.7 C1)."""

from rag.builder import BuildResult, build_rag_index, needs_rebuild
from rag.context_expand import expand_semantic_candidates, task_query_hash
from rag.hybrid import HybridRetriever, create_default_hybrid_retriever, format_hybrid_hits
from rag.models import CodeChunk, RagHit, RagMeta
from rag.query import ensure_rag, get_rag_meta, semantic_search
from rag.store import RagDisabledError, is_rag_enabled

__all__ = [
    "BuildResult",
    "CodeChunk",
    "HybridRetriever",
    "RagDisabledError",
    "RagHit",
    "RagMeta",
    "build_rag_index",
    "create_default_hybrid_retriever",
    "expand_semantic_candidates",
    "ensure_rag",
    "format_hybrid_hits",
    "get_rag_meta",
    "is_rag_enabled",
    "needs_rebuild",
    "semantic_search",
    "task_query_hash",
]
