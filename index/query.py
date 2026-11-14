"""Query API for repo index (v0.6 C1)."""

from __future__ import annotations

from pathlib import Path

import config.settings as settings
from index.builder import build_index, compute_repo_key, needs_rebuild
from index.models import ImportRecord, IndexHit, IndexMeta, ReferenceRecord, SymbolRecord
from index.store import (
    IndexDisabledError,
    connect,
    fetch_file_imports,
    fetch_symbol_definitions,
    fetch_symbol_references,
    is_index_enabled,
    load_index_meta,
)


def get_index_meta(repo_root: Path | None = None) -> IndexMeta | None:
    if not is_index_enabled():
        return None

    repo_key = compute_repo_key(repo_root)
    with connect() as conn:
        return load_index_meta(conn, repo_key)


def ensure_index(repo_root: Path | None = None, *, force: bool = False) -> IndexMeta | None:
    if not is_index_enabled():
        return None

    root = repo_root or settings.REPO_ROOT

    if force or needs_rebuild(root):
        result = build_index(root, force=force)
        if not result.ok:
            return None
        return result.meta

    return get_index_meta(root)


def _definition_hits(records: list[SymbolRecord]) -> list[IndexHit]:
    return [
        IndexHit(
            path=item.path,
            lineno=item.lineno,
            symbol_name=item.name,
            entry_type="definition",
            kind=item.kind,
            qualname=item.qualname,
        )
        for item in records
    ]


def _reference_hits(records: list[ReferenceRecord]) -> list[IndexHit]:
    return [
        IndexHit(
            path=item.path,
            lineno=item.lineno,
            symbol_name=item.symbol_name,
            entry_type="reference",
            context=item.context,
        )
        for item in records
    ]


def _import_hits(records: list[ImportRecord]) -> list[IndexHit]:
    hits: list[IndexHit] = []

    for item in records:
        symbol_name = item.imported_name or item.imported_module.split(".")[-1]
        hits.append(
            IndexHit(
                path=item.path,
                lineno=item.lineno,
                symbol_name=symbol_name,
                entry_type="import",
                imported_module=item.imported_module,
            )
        )

    return hits


def find_symbol_definitions(
    symbol_name: str,
    *,
    repo_root: Path | None = None,
    limit: int | None = None,
    auto_build: bool = True,
) -> list[IndexHit]:
    if not is_index_enabled():
        raise IndexDisabledError("Repo index is disabled (INDEX_ENABLED=0)")

    name = str(symbol_name).strip()
    if not name:
        return []

    root = repo_root or settings.REPO_ROOT
    max_results = limit or settings.DEFAULT_LIST_MAX_RESULTS

    if auto_build:
        ensure_index(root)

    repo_key = compute_repo_key(root)

    with connect() as conn:
        records = fetch_symbol_definitions(conn, repo_key, name, limit=max_results)

    return _definition_hits(records)


def find_symbol_references(
    symbol_name: str,
    *,
    repo_root: Path | None = None,
    limit: int | None = None,
    auto_build: bool = True,
) -> list[IndexHit]:
    if not is_index_enabled():
        raise IndexDisabledError("Repo index is disabled (INDEX_ENABLED=0)")

    name = str(symbol_name).strip()
    if not name:
        return []

    root = repo_root or settings.REPO_ROOT
    max_results = limit or settings.DEFAULT_LIST_MAX_RESULTS

    if auto_build:
        ensure_index(root)

    repo_key = compute_repo_key(root)

    with connect() as conn:
        records = fetch_symbol_references(conn, repo_key, name, limit=max_results)

    return _reference_hits(records)


def find_symbol_hits(
    symbol_name: str,
    *,
    repo_root: Path | None = None,
    limit: int | None = None,
    auto_build: bool = True,
) -> list[IndexHit]:
    definitions = find_symbol_definitions(
        symbol_name,
        repo_root=repo_root,
        limit=limit,
        auto_build=auto_build,
    )
    references = find_symbol_references(
        symbol_name,
        repo_root=repo_root,
        limit=limit,
        auto_build=False,
    )
    return definitions + references


def get_file_import_hits(
    path: str,
    *,
    repo_root: Path | None = None,
    limit: int | None = None,
    auto_build: bool = True,
) -> list[IndexHit]:
    if not is_index_enabled():
        raise IndexDisabledError("Repo index is disabled (INDEX_ENABLED=0)")

    relative_path = str(path).strip().replace("\\", "/")
    if not relative_path:
        return []

    root = repo_root or settings.REPO_ROOT
    max_results = limit or settings.DEFAULT_LIST_MAX_RESULTS

    if auto_build:
        ensure_index(root)

    repo_key = compute_repo_key(root)

    with connect() as conn:
        records = fetch_file_imports(conn, repo_key, relative_path, limit=max_results)

    return _import_hits(records)
