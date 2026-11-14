"""Build repo RAG index (v0.7 C1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import config.settings as settings
from index.builder import compute_repo_key, resolve_head_commit
from rag.chunker import chunk_repo
from rag.embedder import EmbeddingProvider, get_embedding_provider
from rag.models import RagMeta
from rag.store import (
    RagDisabledError,
    delete_repo_chunks,
    is_rag_enabled,
    load_rag_meta,
    save_rag_meta,
    upsert_chunks,
)


@dataclass
class BuildResult:
    ok: bool
    repo_key: str
    meta: RagMeta | None = None
    error: str | None = None
    skipped_files: list[str] | None = None


def needs_rebuild(repo_root: Path | None = None) -> bool:
    if not is_rag_enabled():
        return False

    root = (repo_root or settings.REPO_ROOT).resolve()
    repo_key = compute_repo_key(root)
    meta = load_rag_meta(repo_key)

    if meta is None:
        return True

    if not settings.RAG_AUTO_REBUILD:
        return False

    current_head = resolve_head_commit(root)
    return meta.head_commit != current_head


def build_rag_index(
    repo_root: Path | None = None,
    *,
    force: bool = False,
    embedding_provider: EmbeddingProvider | None = None,
) -> BuildResult:
    if not is_rag_enabled():
        return BuildResult(
            ok=False,
            repo_key="",
            error="Repo RAG is disabled (RAG_ENABLED=0)",
        )

    root = (repo_root or settings.REPO_ROOT).resolve()
    repo_key = compute_repo_key(root)

    if not force and not needs_rebuild(root):
        meta = load_rag_meta(repo_key)
        return BuildResult(ok=True, repo_key=repo_key, meta=meta)

    provider = embedding_provider or get_embedding_provider(force_mock=True)
    chunks, skipped_files = chunk_repo(root)

    if not chunks:
        return BuildResult(
            ok=False,
            repo_key=repo_key,
            error="No indexable chunks found",
            skipped_files=skipped_files,
        )

    try:
        delete_repo_chunks(repo_key)
        embeddings = provider.embed_texts([chunk.text for chunk in chunks])
        head_commit = resolve_head_commit(root)
        upsert_chunks(
            repo_key,
            chunks,
            embeddings,
            head_commit=head_commit,
            embedding_model=provider.model_name,
            embedding_dim=provider.embedding_dim,
        )

        indexed_paths = {chunk.path for chunk in chunks}
        meta = RagMeta(
            repo_key=repo_key,
            head_commit=head_commit,
            rag_version=settings.RAG_VERSION,
            built_at=datetime.now(timezone.utc).isoformat(),
            file_count=len(indexed_paths),
            chunk_count=len(chunks),
            embedding_model=provider.model_name,
            embedding_dim=provider.embedding_dim,
        )
        save_rag_meta(meta)
    except RagDisabledError as exc:
        return BuildResult(ok=False, repo_key=repo_key, error=str(exc))
    except Exception as exc:
        return BuildResult(
            ok=False,
            repo_key=repo_key,
            error="RAG build failed: " + str(exc),
            skipped_files=skipped_files,
        )

    return BuildResult(
        ok=True,
        repo_key=repo_key,
        meta=meta,
        skipped_files=skipped_files,
    )
