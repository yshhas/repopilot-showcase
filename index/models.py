"""Data models for repo index (v0.6 C1)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndexMeta:
    repo_key: str
    head_commit: str | None
    index_version: int
    built_at: str
    file_count: int
    symbol_count: int
    reference_count: int
    import_count: int


@dataclass(frozen=True)
class SymbolRecord:
    path: str
    name: str
    kind: str
    lineno: int
    end_lineno: int | None
    qualname: str


@dataclass(frozen=True)
class ReferenceRecord:
    path: str
    symbol_name: str
    lineno: int
    col_offset: int | None
    context: str


@dataclass(frozen=True)
class ImportRecord:
    path: str
    imported_module: str
    imported_name: str | None
    lineno: int


@dataclass(frozen=True)
class IndexHit:
    """Unified query row for C2 ranking and v0.8 RetrievalHit alignment."""

    path: str
    lineno: int
    symbol_name: str
    entry_type: str
    kind: str | None = None
    qualname: str | None = None
    context: str | None = None
    imported_module: str | None = None
