import json

import config.settings as settings
from tools.change_proposal import _load_context


def test_context_budget_audit_event_metadata_only(isolated_index_repo, monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_ENABLED", True)
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_CHARS", 3000)
    monkeypatch.setattr(settings, "CONTEXT_RANK_MAX_FILES", 1)

    audit_file = isolated_index_repo / "audit.jsonl"
    import audit.audit_log as audit_log_module

    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", audit_file)
    monkeypatch.setattr(audit_log_module, "AUDIT_LOG_FILE", audit_file)

    _load_context("models.py,consumer.py", max_chars=20000)

    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    assert lines

    event = json.loads(lines[-1])
    assert event["event"] == "context_budget_applied"
    assert "candidates_count" in event
    assert "selected_count" in event
    assert "truncated_count" in event
    assert "truncation_reason" in event
    assert "budget_chars" in event
    assert "rank_source" in event

    blob = json.dumps(event, ensure_ascii=False)
    assert "class FileChange" not in blob
    assert "alpha-new" not in blob
