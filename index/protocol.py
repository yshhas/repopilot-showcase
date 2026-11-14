"""Retrieval protocol stubs for v0.8 hybrid search (v0.6 C1 — minimal)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RetrievalHit:
    path: str
    line: int
    score: float
    snippet: str
    backend: str
    symbol_name: str | None = None


class RetrievalBackend(Protocol):
    name: str

    def search(
        self,
        query: str,
        *,
        repo_key: str,
        limit: int,
    ) -> list[RetrievalHit]:
        ...
