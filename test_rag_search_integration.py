import json

import config.settings as settings
from index.builder import build_index
from rag.builder import build_rag_index
from tools.repo_reader import search_in_repo


def test_search_in_repo_rag_disabled_matches_legacy_format(isolated_repo_paths, monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", False)
    monkeypatch.setattr(settings, "RAG_HYBRID_ENABLED", False)

    sample = isolated_repo_paths / "notes.txt"
    sample.write_text("hello legacy search path\n", encoding="utf-8")

    result = search_in_repo("legacy", extensions=".txt")

    assert "检索模式: hybrid" not in result
    assert "匹配数量: 1" in result
    assert "notes.txt:1: hello legacy search path" in result


def test_search_in_repo_rag_disabled_regression_redaction(isolated_repo_paths, monkeypatch):
    _setup_repo = isolated_repo_paths
    monkeypatch.setattr(settings, "RAG_ENABLED", False)

    config_file = _setup_repo / "settings.txt"
    config_file.write_text(
        "api_key = super-long-secret-value\n"
        "public info\n",
        encoding="utf-8",
    )

    result = search_in_repo("api_key", extensions=".txt")

    assert "super-long-secret-value" not in result
    assert "[REDACTED]" in result
    assert "检索模式: hybrid" not in result


def test_search_in_repo_hybrid_mode(isolated_rag_repo, monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", True)
    monkeypatch.setattr(settings, "RAG_HYBRID_ENABLED", True)
    monkeypatch.setattr(settings, "INDEX_ENABLED", True)
    monkeypatch.setattr(settings, "INDEX_DB_FILE", isolated_rag_repo / "database" / "repo_index.db")

    build_index(isolated_rag_repo, force=True)
    build_rag_index(isolated_rag_repo, force=True)

    result = search_in_repo("FileChange", extensions=".py")

    assert "检索模式: hybrid" in result
    assert "匹配数量:" in result
    assert "models.py" in result


def test_search_in_repo_hybrid_writes_audit_metadata_only(isolated_rag_repo, monkeypatch):
    audit_file = isolated_rag_repo / "audit.jsonl"
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", audit_file)
    monkeypatch.setattr(settings, "RAG_ENABLED", True)
    monkeypatch.setattr(settings, "RAG_HYBRID_ENABLED", True)

    import audit.audit_log as audit_log_module

    monkeypatch.setattr(audit_log_module, "AUDIT_LOG_FILE", audit_file)

    build_rag_index(isolated_rag_repo, force=True)
    search_in_repo("FileChange", extensions=".py")

    assert audit_file.exists()
    events = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines()]
    rag_events = [item for item in events if item.get("event") == "rag_query"]

    assert rag_events
    event = rag_events[-1]
    assert event["mode"] == "hybrid_search"
    assert "query_hash" in event
    assert "top_paths" in event
    assert "snippet" not in event


def test_create_default_hybrid_retriever_respects_flags(isolated_rag_repo, monkeypatch):
    from rag.hybrid import create_default_hybrid_retriever

    monkeypatch.setattr(settings, "RAG_ENABLED", False)
    monkeypatch.setattr(settings, "INDEX_ENABLED", False)

    retriever = create_default_hybrid_retriever()
    names = {backend.name for backend in retriever.backends}

    assert names == {"grep"}

    monkeypatch.setattr(settings, "INDEX_ENABLED", True)
    retriever = create_default_hybrid_retriever()
    names = {backend.name for backend in retriever.backends}
    assert names == {"grep", "symbol"}

    monkeypatch.setattr(settings, "RAG_ENABLED", True)
    retriever = create_default_hybrid_retriever()
    names = {backend.name for backend in retriever.backends}
    assert names == {"grep", "symbol", "semantic"}
