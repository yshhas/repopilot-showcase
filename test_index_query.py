from index.builder import build_index
from index.query import (
    find_symbol_definitions,
    find_symbol_hits,
    find_symbol_references,
    get_file_import_hits,
)
from index.store import IndexDisabledError


def test_find_symbol_definitions(isolated_index_repo):
    build_index(isolated_index_repo, force=True)

    hits = find_symbol_definitions("FileChange", repo_root=isolated_index_repo, auto_build=False)

    assert len(hits) >= 1
    hit = hits[0]
    assert hit.entry_type == "definition"
    assert hit.path == "models.py"
    assert hit.symbol_name == "FileChange"
    assert hit.kind == "class"
    assert hit.lineno >= 1


def test_find_symbol_references(isolated_index_repo):
    build_index(isolated_index_repo, force=True)

    hits = find_symbol_references("FileChange", repo_root=isolated_index_repo, auto_build=False)

    assert len(hits) >= 1
    assert any(hit.path == "consumer.py" for hit in hits)
    assert all(hit.entry_type == "reference" for hit in hits)
    assert all(hit.symbol_name == "FileChange" for hit in hits)
    assert all(hit.lineno >= 1 for hit in hits)


def test_find_symbol_hits_combines_definition_and_reference(isolated_index_repo):
    build_index(isolated_index_repo, force=True)

    hits = find_symbol_hits("FileChange", repo_root=isolated_index_repo, auto_build=False)
    entry_types = {hit.entry_type for hit in hits}

    assert "definition" in entry_types
    assert "reference" in entry_types


def test_get_file_import_hits(isolated_index_repo):
    build_index(isolated_index_repo, force=True)

    hits = get_file_import_hits("consumer.py", repo_root=isolated_index_repo, auto_build=False)

    assert len(hits) >= 1
    assert all(hit.entry_type == "import" for hit in hits)
    assert any(hit.imported_module == "models" for hit in hits)


def test_query_auto_build_when_missing(isolated_index_repo):
    hits = find_symbol_definitions("FileChange", repo_root=isolated_index_repo, auto_build=True)

    assert len(hits) >= 1


def test_query_disabled_raises(isolated_index_repo_no_git, monkeypatch):
    import config.settings as settings

    monkeypatch.setattr(settings, "INDEX_ENABLED", False)

    try:
        find_symbol_definitions("FileChange", repo_root=isolated_index_repo_no_git)
    except IndexDisabledError:
        return

    raise AssertionError("expected IndexDisabledError")
