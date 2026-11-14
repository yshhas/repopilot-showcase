from index.protocol import RetrievalHit
from index.ranking import candidates_from_retrieval_hits, rank_file_candidates


def test_candidates_from_retrieval_hits_semantic_only():
    hits = [
        RetrievalHit(
            path="a.py",
            line=10,
            score=0.8,
            snippet="should not appear in candidate",
            backend="semantic",
        ),
        RetrievalHit(
            path="b.py",
            line=3,
            score=0.5,
            snippet="grep",
            backend="grep",
        ),
    ]

    candidates = candidates_from_retrieval_hits(hits)

    assert len(candidates) == 1
    assert candidates[0].path == "a.py"
    assert candidates[0].sources == ["semantic"]
    assert 50.0 <= candidates[0].score <= 70.0


def test_semantic_candidates_rank_below_affected_files():
    from index.ranking import FileCandidate

    semantic = candidates_from_retrieval_hits([
        RetrievalHit(
            path="semantic.py",
            line=1,
            score=1.0,
            snippet="",
            backend="semantic",
        )
    ])
    affected = [FileCandidate(path="affected.py", score=100.0, sources=["affected_files"])]

    ranked = rank_file_candidates(semantic + affected)

    assert ranked[0].path == "affected.py"
