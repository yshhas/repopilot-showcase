import config.settings as settings
from index.builder import build_index, compute_repo_key, needs_rebuild
from index.query import get_index_meta


def test_build_index_creates_meta(isolated_index_repo):
    result = build_index(isolated_index_repo, force=True)

    assert result.ok is True
    assert result.meta is not None
    assert result.meta.symbol_count >= 3
    assert result.meta.file_count >= 2
    assert result.meta.index_version == settings.INDEX_VERSION
    assert result.meta.head_commit is not None
    assert "bad_syntax.py" in (result.skipped_files or [])


def test_build_index_skips_refresh_when_head_unchanged(isolated_index_repo):
    first = build_index(isolated_index_repo, force=True)
    second = build_index(isolated_index_repo, force=False)

    assert first.ok and second.ok
    assert second.meta is not None
    assert second.meta.built_at == first.meta.built_at


def test_needs_rebuild_after_new_commit(isolated_index_repo):
    build_index(isolated_index_repo, force=True)
    assert needs_rebuild(isolated_index_repo) is False

    (isolated_index_repo / "extra.py").write_text("VALUE = 1\n", encoding="utf-8")

    import subprocess

    subprocess.run(["git", "add", "extra.py"], cwd=isolated_index_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "add extra"],
        cwd=isolated_index_repo,
        check=True,
        capture_output=True,
    )

    assert needs_rebuild(isolated_index_repo) is True


def test_compute_repo_key_stable(isolated_index_repo):
    assert compute_repo_key(isolated_index_repo) == compute_repo_key(isolated_index_repo)


def test_get_index_meta_after_build(isolated_index_repo):
    build_index(isolated_index_repo, force=True)
    meta = get_index_meta(isolated_index_repo)

    assert meta is not None
    assert meta.repo_key == compute_repo_key(isolated_index_repo)
