"""Data models for repo RAG (v0.7 C1)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RagMeta:
    repo_key: str
    head_commit: str | None
    rag_version: int
    built_at: str
    file_count: int
    chunk_count: int
    embedding_model: str
    embedding_dim: int


@dataclass(frozen=True)
class CodeChunk:
    path: str
    start_line: int
    end_line: int
    text: str
    symbol_name: str | None
    kind: str
    language: str
    chunk_hash: str


@dataclass(frozen=True)
class RagHit:
    path: str
    start_line: int
    end_line: int
    score: float
    snippet: str
    symbol_name: str | None = None
    kind: str | None = None
