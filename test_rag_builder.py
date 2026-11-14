from pathlib import Path

import config.settings as settings
from index.builder import compute_repo_key
from rag.builder import build_rag_index, needs_rebuild
from rag.chunker import chunk_file
from rag.query import get_rag_meta, semantic_search
from rag.store import RagDisabledError


def test_build_rag_index_creates_meta(isolated_rag_repo):
    result = build_rag_index(isolated_rag_repo, force=True)

    assert result.ok is True
    assert result.meta is not None
    assert result.meta.chunk_count >= 3
    assert result.meta.file_count >= 2
    assert result.meta.rag_version == settings.RAG_VERSION
    assert result.meta.head_commit is not None
    assert result.meta.embedding_model == "mock-deterministic-v1"


def test_build_rag_index_skips_refresh_when_head_unchanged(isolated_rag_repo):
    first = build_rag_index(isolated_rag_repo, force=True)
    second = build_rag_index(isolated_rag_repo, force=False)

    assert first.ok and second.ok
    assert second.meta is not None
    assert second.meta.built_at == first.meta.built_at


def test_needs_rebuild_after_new_commit(isolated_rag_repo):
    build_rag_index(isolated_rag_repo, force=True)
    assert needs_rebuild(isolated_rag_repo) is False

    (isolated_rag_repo / "extra.py").write_text("VALUE = 1\n", encoding="utf-8")

    import subprocess

    subprocess.run(["git", "add", "extra.py"], cwd=isolated_rag_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "add extra"],
        cwd=isolated_rag_repo,
        check=True,
        capture_output=True,
    )

    assert needs_rebuild(isolated_rag_repo) is True


def test_semantic_search_returns_hits(isolated_rag_repo):
    result = build_rag_index(isolated_rag_repo, force=True)
    assert result.meta is not None

    chunks = chunk_file(isolated_rag_repo, Path("models.py"))
    assert chunks

    hits = semantic_search(
        chunks[0].text,
        repo_root=isolated_rag_repo,
        limit=5,
        auto_build=False,
    )

    assert hits
    assert hits[0].path == "models.py"


def test_get_rag_meta_after_build(isolated_rag_repo):
    build_rag_index(isolated_rag_repo, force=True)
    meta = get_rag_meta(isolated_rag_repo)

    assert meta is not None
    assert meta.repo_key == compute_repo_key(isolated_rag_repo)


def test_build_disabled_returns_error(isolated_rag_repo, monkeypatch):
    import config.settings as settings

    monkeypatch.setattr(settings, "RAG_ENABLED", False)

    result = build_rag_index(isolated_rag_repo, force=True)

    assert result.ok is False
    assert "disabled" in (result.error or "").lower()


def test_semantic_search_disabled_raises(isolated_rag_repo, monkeypatch):
    import config.settings as settings

    monkeypatch.setattr(settings, "RAG_ENABLED", False)

    try:
        semantic_search("anything", repo_root=isolated_rag_repo)
        raised = False
    except RagDisabledError:
        raised = True

    assert raised is True
