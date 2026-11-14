"""Chroma vector persistence for repo RAG (v0.7 C1)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import config.settings as settings
from rag.models import CodeChunk, RagHit, RagMeta

logger = logging.getLogger(__name__)


class RagDisabledError(RuntimeError):
    pass


def is_rag_enabled() -> bool:
    return bool(settings.RAG_ENABLED)


def ensure_enabled() -> None:
    if not is_rag_enabled():
        raise RagDisabledError("Repo RAG is disabled (RAG_ENABLED=0)")


def vector_dir() -> Path:
    return Path(settings.RAG_VECTOR_DIR)


def meta_file_path() -> Path:
    return vector_dir() / "rag_meta.json"


def _load_meta_map() -> dict[str, dict]:
    path = meta_file_path()
    if not path.exists():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(raw, dict):
        return {}

    return raw


def _save_meta_map(data: dict[str, dict]) -> None:
    path = meta_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_rag_meta(meta: RagMeta) -> None:
    ensure_enabled()
    data = _load_meta_map()
    data[meta.repo_key] = {
        "repo_key": meta.repo_key,
        "head_commit": meta.head_commit,
        "rag_version": meta.rag_version,
        "built_at": meta.built_at,
        "file_count": meta.file_count,
        "chunk_count": meta.chunk_count,
        "embedding_model": meta.embedding_model,
        "embedding_dim": meta.embedding_dim,
    }
    _save_meta_map(data)


def load_rag_meta(repo_key: str) -> RagMeta | None:
    ensure_enabled()
    raw = _load_meta_map().get(repo_key)
    if raw is None:
        return None

    return RagMeta(
        repo_key=raw["repo_key"],
        head_commit=raw.get("head_commit"),
        rag_version=int(raw["rag_version"]),
        built_at=str(raw["built_at"]),
        file_count=int(raw["file_count"]),
        chunk_count=int(raw["chunk_count"]),
        embedding_model=str(raw["embedding_model"]),
        embedding_dim=int(raw["embedding_dim"]),
    )


def _chunk_id(repo_key: str, chunk: CodeChunk) -> str:
    return repo_key + ":" + chunk.chunk_hash


def _get_collection(*, embedding_function=None):
    import chromadb

    directory = vector_dir()
    directory.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(directory))

    kwargs = {"name": settings.RAG_COLLECTION_NAME}
    if embedding_function is not None:
        kwargs["embedding_function"] = embedding_function

    return client.get_or_create_collection(**kwargs)


def delete_repo_chunks(repo_key: str) -> None:
    ensure_enabled()

    directory = vector_dir()
    if not directory.exists():
        return

    try:
        collection = _get_collection()
    except Exception as e:
        logger.warning("获取 RAG collection 失败: %s", e, exc_info=True)
        return

    try:
        collection.delete(where={"repo_key": repo_key})
    except Exception as e:
        logger.warning("删除 RAG collection 数据失败: %s", e, exc_info=True)
        return

    data = _load_meta_map()
    if repo_key in data:
        del data[repo_key]
        _save_meta_map(data)


def upsert_chunks(
    repo_key: str,
    chunks: list[CodeChunk],
    embeddings: list[list[float]],
    *,
    head_commit: str | None,
    embedding_model: str,
    embedding_dim: int,
) -> None:
    ensure_enabled()

    if len(chunks) != len(embeddings):
        raise ValueError("chunks and embeddings length mismatch")

    collection = _get_collection()

    ids = [_chunk_id(repo_key, chunk) for chunk in chunks]
    documents = [chunk.text for chunk in chunks]
    metadatas = [
        {
            "repo_key": repo_key,
            "path": chunk.path,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "symbol_name": chunk.symbol_name or "",
            "kind": chunk.kind,
            "language": chunk.language,
            "head_commit": head_commit or "",
            "chunk_hash": chunk.chunk_hash,
            "embedding_model": embedding_model,
            "embedding_dim": embedding_dim,
        }
        for chunk in chunks
    ]

    if ids:
        collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )


def query_similar(
    repo_key: str,
    query_embedding: list[float],
    *,
    limit: int,
) -> list[RagHit]:
    ensure_enabled()

    collection = _get_collection()
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=limit,
        where={"repo_key": repo_key},
        include=["documents", "metadatas", "distances"],
    )

    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    hits: list[RagHit] = []

    for document, metadata, distance in zip(documents, metadatas, distances):
        if not metadata:
            continue

        from context._shared import truncate_text
        snippet = truncate_text(document or "", 200)

        symbol_name = metadata.get("symbol_name") or None
        if symbol_name == "":
            symbol_name = None

        score = 1.0 / (1.0 + float(distance or 0.0))
        hits.append(
            RagHit(
                path=str(metadata.get("path") or ""),
                start_line=int(metadata.get("start_line") or 0),
                end_line=int(metadata.get("end_line") or 0),
                score=score,
                snippet=snippet,
                symbol_name=symbol_name,
                kind=str(metadata.get("kind") or "") or None,
            )
        )

    return hits


def count_repo_chunks(repo_key: str) -> int:
    ensure_enabled()
    collection = _get_collection()
    result = collection.get(where={"repo_key": repo_key}, include=[])
    ids = result.get("ids") or []
    return len(ids)
