from index.protocol import RetrievalHit
from rag.hybrid import HybridRetriever


class _StaticBackend:
    def __init__(self, name: str, hits: list[RetrievalHit]):
        self.name = name
        self._hits = hits

    def search(
        self,
        query: str,
        *,
        repo_key: str,
        limit: int,
        path: str = "",
        extensions: str = "",
    ) -> list[RetrievalHit]:
        del query, repo_key, path, extensions
        return self._hits[:limit]


def test_hybrid_merge_rank_dedupes_by_path_and_line():
    retriever = HybridRetriever([
        _StaticBackend(
            "grep",
            [
                RetrievalHit(
                    path="a.py",
                    line=10,
                    score=0.4,
                    snippet="grep hit",
                    backend="grep",
                )
            ],
        ),
        _StaticBackend(
            "semantic",
            [
                RetrievalHit(
                    path="a.py",
                    line=10,
                    score=0.6,
                    snippet="semantic hit",
                    backend="semantic",
                ),
                RetrievalHit(
                    path="b.py",
                    line=3,
                    score=0.55,
                    snippet="other",
                    backend="semantic",
                ),
            ],
        ),
    ])

    hits = retriever.merge_rank("retry", repo_key="repo", limit=5)

    assert len(hits) == 2
    assert hits[0].path == "a.py"
    assert hits[0].line == 10
    assert hits[0].score > 0.6
    assert "+" in hits[0].backend


def test_hybrid_merge_rank_orders_by_score():
    retriever = HybridRetriever([
        _StaticBackend(
            "symbol",
            [
                RetrievalHit(
                    path="high.py",
                    line=1,
                    score=0.9,
                    snippet="symbol",
                    backend="symbol",
                    symbol_name="Target",
                )
            ],
        ),
        _StaticBackend(
            "grep",
            [
                RetrievalHit(
                    path="low.py",
                    line=2,
                    score=0.4,
                    snippet="grep",
                    backend="grep",
                )
            ],
        ),
    ])

    hits = retriever.merge_rank("Target", repo_key="repo", limit=5)

    assert [hit.path for hit in hits] == ["high.py", "low.py"]
