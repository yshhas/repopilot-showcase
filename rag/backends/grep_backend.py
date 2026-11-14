"""Grep retrieval backend (v0.7 C2)."""

from __future__ import annotations

import os
from pathlib import Path

from config.settings import DEFAULT_SEARCH_MAX_RESULTS
from context.project_context import get_repo_root
from index.protocol import RetrievalHit
from security.path_guard import (
    is_allowed_extension,
    is_blocked_file,
    is_ignored_dir,
    parse_extensions,
    resolve_repo_path,
)
from security.redaction import redact_text


class GrepBackend:
    name = "grep"

    def search(
        self,
        query: str,
        *,
        repo_key: str,
        limit: int,
        path: str = "",
        extensions: str = "",
    ) -> list[RetrievalHit]:
        del repo_key
        return grep_search_hits(
            query,
            path=path,
            extensions=extensions,
            max_results=limit,
        )


def _iter_search_files(root: Path, ext_filter: set[str]) -> list[Path]:
    if root.is_file():
        return [root]

    if not root.is_dir():
        return []

    files: list[Path] = []

    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not is_ignored_dir(name)]

        for filename in filenames:
            file_path = Path(current_root) / filename

            if is_blocked_file(file_path):
                continue

            if not is_allowed_extension(file_path, ext_filter):
                continue

            files.append(file_path)

    return files


def grep_search_hits(
    keyword: str,
    *,
    path: str = "",
    extensions: str = "",
    max_results: int | None = None,
) -> list[RetrievalHit]:
    text = str(keyword or "").strip()
    if not text:
        return []

    limit = max_results or DEFAULT_SEARCH_MAX_RESULTS
    root = resolve_repo_path(path)
    ext_filter = parse_extensions(extensions)
    files = _iter_search_files(root, ext_filter)

    hits: list[RetrievalHit] = []

    for file_path in files:
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue

        rel = str(file_path.relative_to(get_repo_root())).replace("\\", "/")

        for line_no, line in enumerate(lines, start=1):
            if text.lower() not in line.lower():
                continue

            safe_line = redact_text(line.strip())
            rank_boost = 1.0 - min(0.3, (len(hits) / max(1, limit)) * 0.3)

            hits.append(
                RetrievalHit(
                    path=rel,
                    line=line_no,
                    score=0.4 * rank_boost,
                    snippet=safe_line,
                    backend="grep",
                )
            )

            if len(hits) >= limit:
                return hits

    return hits


def format_grep_legacy_matches(hits: list[RetrievalHit]) -> list[str]:
    return [hit.path + ":" + str(hit.line) + ": " + hit.snippet for hit in hits]
