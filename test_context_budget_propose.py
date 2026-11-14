
import config.settings as settings
from tools.change_proposal import _load_context, _load_context_legacy


def test_load_context_legacy_without_budget(isolated_index_repo, monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_ENABLED", False)

    result = _load_context("models.py,consumer.py", max_chars=20000)

    assert "===== 文件: models.py =====" in result
    assert "===== 文件: consumer.py =====" in result
    assert "上下文选择摘要" not in result


def test_load_context_with_budget_writes_summary(isolated_index_repo, monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_ENABLED", True)
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_CHARS", 5000)
    monkeypatch.setattr(settings, "CONTEXT_RANK_MAX_FILES", 1)

    result = _load_context(
        "models.py,consumer.py",
        max_chars=20000,
        affected_files=["consumer.py"],
    )

    assert "===== 上下文选择摘要 =====" in result
    assert "候选文件:" in result
    assert "跳过原因:" in result


def test_load_context_budget_disabled_matches_legacy(isolated_index_repo, monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_ENABLED", False)

    legacy = _load_context_legacy("models.py", max_chars=20000)
    wrapped = _load_context("models.py", max_chars=20000)

    assert wrapped == legacy
