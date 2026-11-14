import config.settings as settings
from tools.repo_analyzer import find_file_dependencies


def test_ffd_symbol_disabled_message(isolated_index_repo, monkeypatch):
    monkeypatch.setattr(settings, "INDEX_ENABLED", False)

    result = find_file_dependencies(symbol="FileChange", query_mode="symbol")

    assert "INDEX_ENABLED=0" in result
    assert "Symbol 查询不可用" in result


def test_ffd_dependencies_still_works_when_index_disabled(isolated_index_repo, monkeypatch):
    monkeypatch.setattr(settings, "INDEX_ENABLED", False)

    result = find_file_dependencies(path="consumer.py", query_mode="dependencies")

    assert "===== 本文件 import =====" in result
    assert "models" in result
