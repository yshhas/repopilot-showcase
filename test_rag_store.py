from rag.chunker import chunk_python_source
from rag.embedder import MockEmbeddingProvider
from rag.models import RagMeta
from rag.store import (
    RagDisabledError,
    count_repo_chunks,
    load_rag_meta,
    query_similar,
    save_rag_meta,
    upsert_chunks,
)


def test_store_upsert_and_query(isolated_rag_repo):
    repo_key = "test-repo-key"
    provider = MockEmbeddingProvider()
    chunks = chunk_python_source(
        "service.py",
        "def retry_operation():\n    return 'retry'\n",
    )
    embeddings = provider.embed_texts([chunk.text for chunk in chunks])

    upsert_chunks(
        repo_key,
        chunks,
        embeddings,
        head_commit="abc123",
        embedding_model=provider.model_name,
        embedding_dim=provider.embedding_dim,
    )

    save_rag_meta(
        RagMeta(
            repo_key=repo_key,
            head_commit="abc123",
            rag_version=1,
            built_at="2026-07-20T00:00:00+00:00",
            file_count=1,
            chunk_count=len(chunks),
            embedding_model=provider.model_name,
            embedding_dim=provider.embedding_dim,
        )
    )

    meta = load_rag_meta(repo_key)
    assert meta is not None
    assert meta.chunk_count == len(chunks)
    assert count_repo_chunks(repo_key) == len(chunks)

    hits = query_similar(
        repo_key,
        provider.embed_query(chunks[0].text),
        limit=3,
    )

    assert hits
    assert hits[0].path == "service.py"
    assert hits[0].score > 0


def test_store_disabled_raises(tmp_path, monkeypatch):
    import config.settings as settings

    monkeypatch.setattr(settings, "RAG_ENABLED", False)

    try:
        load_rag_meta("any")
        raised = False
    except RagDisabledError:
        raised = True

    assert raised is True
