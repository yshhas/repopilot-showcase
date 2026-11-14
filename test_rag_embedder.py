from rag.embedder import MockEmbeddingProvider


def test_mock_embedding_provider_is_deterministic():
    provider = MockEmbeddingProvider(embedding_dim=16)

    first = provider.embed_query("context budget truncation")
    second = provider.embed_query("context budget truncation")
    different = provider.embed_query("git rollback safety")

    assert first == second
    assert first != different
    assert len(first) == 16


def test_mock_embedding_provider_batch_matches_single():
    provider = MockEmbeddingProvider(embedding_dim=8)
    texts = ["alpha", "beta"]

    batch = provider.embed_texts(texts)

    assert len(batch) == 2
    assert batch[0] == provider.embed_query("alpha")
    assert batch[1] == provider.embed_query("beta")
