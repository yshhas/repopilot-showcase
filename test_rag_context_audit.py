import json
from pathlib import Path

import config.settings as settings
from rag.builder import build_rag_index
from rag.chunker import chunk_file
from tools.change_proposal import _load_context


def test_rag_context_expand_audit_metadata_only(isolated_rag_repo, monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", True)
    monkeypatch.setattr(settings, "RAG_CONTEXT_EXPAND", True)
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_ENABLED", True)

    audit_file = isolated_rag_repo / "audit.jsonl"
    import audit.audit_log as audit_log_module

    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", audit_file)
    monkeypatch.setattr(audit_log_module, "AUDIT_LOG_FILE", audit_file)

    build_rag_index(isolated_rag_repo, force=True)
    chunks = chunk_file(isolated_rag_repo, Path("models.py"))

    _load_context(
        "consumer.py",
        max_chars=20000,
        task_description=chunks[0].text,
    )

    events = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines()]
    expand_events = [item for item in events if item.get("event") == "rag_context_expand"]
    budget_events = [item for item in events if item.get("event") == "context_budget_applied"]

    assert expand_events
    expand = expand_events[-1]
    assert "task_hash" in expand
    assert "candidate_count" in expand
    assert "candidate_paths" in expand
    assert "embedding" not in json.dumps(expand, ensure_ascii=False).lower()
    assert "def " not in json.dumps(expand, ensure_ascii=False)

    assert budget_events
    budget = budget_events[-1]
    assert "semantic" in budget.get("rank_source", "")
    blob = json.dumps(budget, ensure_ascii=False)
    assert "class FileChange" not in blob
