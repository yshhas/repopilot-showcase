import config.settings as settings
from tools.git_tools import git_create_backup
from tools.patch_apply import apply_repo_patch
from tools.result_schema import tool_result_message


def test_apply_repo_patch_updates_existing_file(isolated_git_repo):
    git_create_backup()

    result = apply_repo_patch("sample.txt", "updated content\n")

    assert "Patch 应用完成" in tool_result_message(result)

    assert (
        isolated_git_repo / "sample.txt"
    ).read_text(encoding="utf-8") == "updated content\n"


def test_apply_repo_patch_creates_new_file(isolated_git_repo):
    git_create_backup()

    result = apply_repo_patch("new_file.txt", "first line\n")

    assert "Patch 应用完成" in tool_result_message(result)

    assert "新建" in tool_result_message(result)

    assert (
        isolated_git_repo / "new_file.txt"
    ).read_text(encoding="utf-8") == "first line\n"


def test_apply_repo_patch_rejects_without_backup(isolated_git_repo):
    result = apply_repo_patch("sample.txt", "updated content\n")

    assert "备份" in tool_result_message(result)

    assert (
        isolated_git_repo / "sample.txt"
    ).read_text(encoding="utf-8") == "original\n"


def test_apply_repo_patch_allows_without_backup_when_not_required(
    isolated_git_repo,
    monkeypatch,
):
    monkeypatch.setattr(settings, "PATCH_REQUIRE_BACKUP", False)

    result = apply_repo_patch("sample.txt", "updated content\n")

    assert "Patch 应用完成" in tool_result_message(result)

    assert "无备份记录" in tool_result_message(result)

    assert (
        isolated_git_repo / "sample.txt"
    ).read_text(encoding="utf-8") == "updated content\n"


def test_apply_repo_patch_rejects_no_change(isolated_git_repo):
    git_create_backup()

    result = apply_repo_patch("sample.txt", "original\n")

    assert "无变化" in tool_result_message(result)


def test_apply_repo_patch_rejects_sensitive_path(isolated_git_repo):
    git_create_backup()

    env_file = isolated_git_repo / ".env"

    env_file.write_text("SECRET=1\n", encoding="utf-8")

    result = apply_repo_patch(".env", "SECRET=2\n")

    assert "敏感" in tool_result_message(result)


def test_apply_repo_patch_rejects_path_traversal(isolated_git_repo):
    git_create_backup()

    result = apply_repo_patch("../outside.txt", "bad\n")

    assert "越界" in tool_result_message(result)


def test_apply_repo_patch_leaves_file_unchanged_when_check_fails(
    isolated_git_repo,
    monkeypatch,
):
    git_create_backup()

    import tools.patch_apply as patch_apply_module

    original_run_git = patch_apply_module._run_git

    def fake_run_git(args, *, input_text=None):
        if args == ["apply", "--check", "-"]:
            return False, "simulated check failure"

        return original_run_git(args, input_text=input_text)

    monkeypatch.setattr(patch_apply_module, "_run_git", fake_run_git)

    result = apply_repo_patch("sample.txt", "updated content\n")

    assert "预检失败" in tool_result_message(result)

    assert (
        isolated_git_repo / "sample.txt"
    ).read_text(encoding="utf-8") == "original\n"


def test_apply_repo_patch_does_not_auto_rollback_when_apply_fails(
    isolated_git_repo,
    monkeypatch,
):
    git_create_backup()

    import tools.patch_apply as patch_apply_module

    original_run_git = patch_apply_module._run_git

    def fake_run_git(args, *, input_text=None):
        if args == ["apply", "--check", "-"]:
            return True, ""

        if args == ["apply", "-"]:
            return False, "simulated apply failure"

        return original_run_git(args, input_text=input_text)

    monkeypatch.setattr(patch_apply_module, "_run_git", fake_run_git)

    result = apply_repo_patch("sample.txt", "updated content\n")

    assert "patch 应用失败" in tool_result_message(result)

    assert (
        isolated_git_repo / "sample.txt"
    ).read_text(encoding="utf-8") == "original\n"


def test_apply_repo_patch_uses_git_apply_check_before_apply(
    isolated_git_repo,
    monkeypatch,
):
    git_create_backup()

    import tools.patch_apply as patch_apply_module

    calls: list[list[str]] = []

    original_run_git = patch_apply_module._run_git

    def tracking_run_git(args, *, input_text=None):
        calls.append(list(args))

        return original_run_git(args, input_text=input_text)

    monkeypatch.setattr(patch_apply_module, "_run_git", tracking_run_git)

    apply_repo_patch("sample.txt", "updated content\n")

    check_index = next(
        i for i, args in enumerate(calls) if args == ["apply", "--check", "-"]
    )

    apply_index = next(i for i, args in enumerate(calls) if args == ["apply", "-"])

    assert check_index < apply_index
