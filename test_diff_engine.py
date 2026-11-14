
from tools.diff_engine import (
    DiffValidationResult,
    build_unified_diff,
    normalize_new_content,
    read_repo_text_for_diff,
    summarize_diff,
    validate_diff_text,
)


def test_normalize_new_content_converts_crlf():

    assert normalize_new_content("a\r\nb") == "a\nb"


def test_build_unified_diff_single_line_change():

    diff = build_unified_diff(
        "test.txt",
        "hello\n",
        "hello world\n",
    )

    assert "--- a/test.txt" in diff

    assert "+++ b/test.txt" in diff

    assert "-hello" in diff

    assert "+hello world" in diff


def test_build_unified_diff_new_file():

    diff = build_unified_diff(
        "new.txt",
        "",
        "first line\n",
    )

    assert "--- a/new.txt" in diff

    assert "+first line" in diff


def test_validate_rejects_empty_diff():

    result = validate_diff_text(
        "",
        path="same.txt",
        old_text="x\n",
        new_text="x\n",
    )

    assert result.ok is False

    assert "无变化" in result.error


def test_validate_accepts_consistent_diff():

    old_text = "line1\nline2\n"

    new_text = "line1\nline2 changed\n"

    diff = build_unified_diff("foo.py", old_text, new_text)

    result = validate_diff_text(
        diff,
        path="foo.py",
        old_text=old_text,
        new_text=new_text,
    )

    assert result == DiffValidationResult(True, "")


def test_validate_rejects_mismatched_diff():

    old_text = "a\n"

    new_text = "b\n"

    diff = build_unified_diff("file.txt", old_text, new_text)

    result = validate_diff_text(
        diff,
        path="other.txt",
        old_text=old_text,
        new_text=new_text,
    )

    assert result.ok is False


def test_validate_rejects_too_many_hunks(monkeypatch):

    import config.settings as settings

    monkeypatch.setattr(settings, "PATCH_MAX_HUNKS", 1)

    old_text = "\n".join("line" + str(i) for i in range(30)) + "\n"

    new_lines = [
        "CHANGED" + str(i) if i in (0, 15, 29) else "line" + str(i)
        for i in range(30)
    ]

    new_text = "\n".join(new_lines) + "\n"

    diff = build_unified_diff("big.txt", old_text, new_text)

    result = validate_diff_text(
        diff,
        path="big.txt",
        old_text=old_text,
        new_text=new_text,
    )

    assert result.ok is False

    assert "hunk" in result.error.lower()


def test_summarize_diff_counts_lines():

    diff = build_unified_diff("x.txt", "a\n", "b\n")

    summary = summarize_diff(diff)

    assert summary["hunk_count"] >= 1

    assert summary["lines_added"] == 1

    assert summary["lines_removed"] == 1

    assert "preview" in summary


def _setup_repo(tmp_path, monkeypatch):

    monkeypatch.setenv("REPO_ROOT", str(tmp_path))

    import config.settings as settings

    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)

    import context.project_context as project_context_module

    monkeypatch.setattr(project_context_module, "REPO_ROOT", tmp_path)

    import security.path_guard as path_guard

    monkeypatch.setattr(path_guard, "REPO_ROOT", tmp_path)


def test_read_repo_text_for_diff_existing_file(tmp_path, monkeypatch):

    _setup_repo(tmp_path, monkeypatch)

    sample = tmp_path / "sample.txt"

    sample.write_text("hello repo\n", encoding="utf-8")

    content, error = read_repo_text_for_diff("sample.txt")

    assert error is None

    assert content == "hello repo\n"


def test_read_repo_text_for_diff_missing_file_returns_empty(tmp_path, monkeypatch):

    _setup_repo(tmp_path, monkeypatch)

    content, error = read_repo_text_for_diff("new_file.txt")

    assert error is None

    assert content == ""


def test_read_repo_text_for_diff_blocks_env(tmp_path, monkeypatch):

    _setup_repo(tmp_path, monkeypatch)

    env_file = tmp_path / ".env"

    env_file.write_text("SECRET=1\n", encoding="utf-8")

    content, error = read_repo_text_for_diff(".env")

    assert content is None

    assert "敏感" in error


def test_read_repo_text_for_diff_blocks_path_traversal(tmp_path, monkeypatch):

    _setup_repo(tmp_path, monkeypatch)

    content, error = read_repo_text_for_diff("../outside.txt")

    assert content is None

    assert "越界" in error
