"""Symbol index retrieval backend (v0.7 C2)."""

from __future__ import annotations

import logging
import re

import config.settings as settings
from index.protocol import RetrievalHit
from index.query import find_symbol_definitions, find_symbol_references

logger = logging.getLogger(__name__)


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


def looks_like_symbol_query(query: str) -> bool:
    token = str(query or "").strip().split()[0]
    if not token:
        return False
    return bool(_IDENTIFIER_RE.match(token))


class SymbolBackend:
    name = "symbol"

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

        if not settings.INDEX_ENABLED:
            return []

        token = str(query or "").strip().split()[0]
        if not looks_like_symbol_query(token):
            return []

        per_kind_limit = max(1, limit)
        hits: list[RetrievalHit] = []

        try:
            definitions = find_symbol_definitions(token, limit=per_kind_limit)
            references = find_symbol_references(token, limit=per_kind_limit, auto_build=False)
        except Exception as e:
            logger.warning("符号索引检索失败: %s", e, exc_info=True)
            return []

        for item in definitions:
            snippet = item.qualname or item.symbol_name
            if item.kind:
                snippet = "[" + item.kind + "] " + snippet

            hits.append(
                RetrievalHit(
                    path=item.path,
                    line=item.lineno,
                    score=0.9,
                    snippet=snippet,
                    backend="symbol",
                    symbol_name=item.symbol_name,
                )
            )

        for item in references:
            snippet = item.context or item.symbol_name
            hits.append(
                RetrievalHit(
                    path=item.path,
                    line=item.lineno,
                    score=0.8,
                    snippet=snippet,
                    backend="symbol",
                    symbol_name=item.symbol_name,
                )
            )

        return hits[:limit]
