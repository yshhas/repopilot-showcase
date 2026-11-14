from index.protocol import RetrievalBackend, RetrievalHit


def test_retrieval_hit_dataclass():
    hit = RetrievalHit(
        path="models.py",
        line=1,
        score=1.0,
        snippet="class FileChange",
        backend="symbol",
        symbol_name="FileChange",
    )

    assert hit.path == "models.py"
    assert hit.backend == "symbol"


def test_retrieval_backend_protocol_shape():
    assert hasattr(RetrievalBackend, "search")
