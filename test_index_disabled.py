import config.settings as settings
from index.builder import build_index, needs_rebuild
from index.query import find_symbol_definitions, get_index_meta
from index.store import IndexDisabledError, connect, is_index_enabled


def test_index_disabled_build_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(settings, "INDEX_DB_FILE", tmp_path / "database" / "repo_index.db")
    monkeypatch.setattr(settings, "INDEX_ENABLED", False)

    result = build_index(tmp_path, force=True)

    assert result.ok is False
    assert "disabled" in (result.error or "").lower()
    assert not (tmp_path / "database" / "repo_index.db").exists()


def test_index_disabled_connect_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "INDEX_DB_FILE", tmp_path / "database" / "repo_index.db")
    monkeypatch.setattr(settings, "INDEX_ENABLED", False)

    try:
        connect()
    except IndexDisabledError:
        return

    raise AssertionError("expected IndexDisabledError")


def test_index_disabled_query_meta_none(isolated_index_repo_no_git, monkeypatch):
    monkeypatch.setattr(settings, "INDEX_ENABLED", False)

    assert is_index_enabled() is False
    assert get_index_meta(isolated_index_repo_no_git) is None
    assert needs_rebuild(isolated_index_repo_no_git) is False

    try:
        find_symbol_definitions("FileChange", repo_root=isolated_index_repo_no_git)
    except IndexDisabledError:
        return

    raise AssertionError("expected IndexDisabledError")
