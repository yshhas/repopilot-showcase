"""Repo index package (v0.6 C1)."""

from index.builder import BuildResult, build_index, compute_repo_key, needs_rebuild
from index.models import IndexHit, IndexMeta
from index.query import (
    ensure_index,
    find_symbol_definitions,
    find_symbol_hits,
    find_symbol_references,
    get_file_import_hits,
    get_index_meta,
)
from index.store import IndexDisabledError, is_index_enabled

__all__ = [
    "BuildResult",
    "IndexDisabledError",
    "IndexHit",
    "IndexMeta",
    "build_index",
    "compute_repo_key",
    "ensure_index",
    "find_symbol_definitions",
    "find_symbol_hits",
    "find_symbol_references",
    "get_file_import_hits",
    "get_index_meta",
    "is_index_enabled",
    "needs_rebuild",
]
