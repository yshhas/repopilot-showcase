import config.settings as settings
from tools.change_proposal import _load_context


def test_affected_files_prioritized_in_budget_path(isolated_index_repo, monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_ENABLED", True)
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_CHARS", 80000)
    monkeypatch.setattr(settings, "CONTEXT_RANK_MAX_FILES", 1)

    result = _load_context(
        "models.py",
        max_chars=20000,
        affected_files=["consumer.py"],
    )

    assert "===== 文件: consumer.py =====" in result
    assert "rank_source" in result
    assert "affected_files" in result
