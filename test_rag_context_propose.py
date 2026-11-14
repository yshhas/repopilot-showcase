import json
from pathlib import Path

import config.settings as settings
from rag.builder import build_rag_index
from rag.chunker import chunk_file
from tools.change_proposal import _load_context


def test_semantic_expand_adds_task_candidates(isolated_rag_repo, monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", True)
    monkeypatch.setattr(settings, "RAG_CONTEXT_EXPAND", True)
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_ENABLED", True)
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_CHARS", 80000)

    build_rag_index(isolated_rag_repo, force=True)
    chunks = chunk_file(isolated_rag_repo, Path("models.py"))
    assert chunks

    result = _load_context(
        "consumer.py",
        max_chars=20000,
        task_description=chunks[0].text,
    )

    assert "rank_source:" in result
    assert "semantic" in result.split("rank_source:")[-1]
    assert "models.py" in result
    assert "===== 文件:" in result


def test_semantic_expand_uses_read_repo_file_not_chunk_text(isolated_rag_repo, monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", True)
    monkeypatch.setattr(settings, "RAG_CONTEXT_EXPAND", True)
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_ENABLED", True)

    build_rag_index(isolated_rag_repo, force=True)
    chunks = chunk_file(isolated_rag_repo, Path("models.py"))

    result = _load_context(
        "models.py",
        max_chars=20000,
        task_description=chunks[0].text,
    )

    assert "项目:" in result
    assert "===== 文件: models.py =====" in result
    assert "# path: models.py" not in result.split("===== 文件: models.py =====")[-1][:200]


def test_semantic_expand_skipped_when_rag_disabled(isolated_rag_repo, monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", False)
    monkeypatch.setattr(settings, "RAG_CONTEXT_EXPAND", True)
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_ENABLED", True)

    audit_file = isolated_rag_repo / "audit.jsonl"
    import audit.audit_log as audit_log_module

    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", audit_file)
    monkeypatch.setattr(audit_log_module, "AUDIT_LOG_FILE", audit_file)

    result = _load_context(
        "models.py",
        max_chars=20000,
        task_description="FileChange validate method",
    )

    assert "rank_source:" in result
    assert "semantic" not in result.split("rank_source:")[-1]

    if audit_file.exists():
        events = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines()]
        assert not any(item.get("event") == "rag_context_expand" for item in events)


def test_rag_disabled_matches_v06_context_budget(isolated_index_repo, monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", False)
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_ENABLED", True)
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_CHARS", 80000)
    monkeypatch.setattr(settings, "CONTEXT_RANK_MAX_FILES", 1)

    without_task = _load_context(
        "models.py",
        max_chars=20000,
        affected_files=["consumer.py"],
    )
    with_task = _load_context(
        "models.py",
        max_chars=20000,
        affected_files=["consumer.py"],
        task_description="unrelated natural language query",
    )

    assert without_task == with_task
