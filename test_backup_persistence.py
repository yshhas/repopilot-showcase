import json

import subprocess

from context import project_context
from tools.git_tools import git_create_backup, git_rollback
from tools.result_schema import tool_result_message


def _setup_repo(tmp_path, monkeypatch):

    monkeypatch.setenv("REPO_ROOT", str(tmp_path))

    import config.settings as settings

    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)

    monkeypatch.setattr(settings, "BACKUP_STATE_FILE", tmp_path / "last_backup.json")

    import context.project_context as project_context_module

    monkeypatch.setattr(project_context_module, "REPO_ROOT", tmp_path)

    monkeypatch.setattr(
        project_context_module,
        "BACKUP_STATE_FILE",
        tmp_path / "last_backup.json",
    )

    import security.path_guard as path_guard

    monkeypatch.setattr(path_guard, "REPO_ROOT", tmp_path)

    import tools.git_tools as git_tools_module

    monkeypatch.setattr(git_tools_module, "REPO_ROOT", tmp_path)

    project_context._last_backup_branch = None

    project_context._last_backup_commit = None

    project_context._last_original_branch = None

    if settings.BACKUP_STATE_FILE.exists():

        settings.BACKUP_STATE_FILE.unlink()


    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    sample = tmp_path / "sample.txt"

    sample.write_text("original\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)

    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )


def test_set_backup_info_writes_last_backup_json(tmp_path, monkeypatch):

    _setup_repo(tmp_path, monkeypatch)

    git_create_backup()

    import config.settings as settings

    assert settings.BACKUP_STATE_FILE.exists()

    data = json.loads(
        settings.BACKUP_STATE_FILE.read_text(encoding="utf-8")
    )

    assert data["repo_root"] == str(tmp_path)

    assert data["backup_branch"].startswith("agent-backup/")

    assert data["backup_commit"]

    assert data["original_branch"]


def test_get_backup_info_loads_from_disk_after_memory_reset(tmp_path, monkeypatch):

    _setup_repo(tmp_path, monkeypatch)

    git_create_backup()

    project_context._last_backup_branch = None

    project_context._last_backup_commit = None

    project_context._last_original_branch = None

    info = project_context.get_backup_info()

    assert info["backup_branch"]

    assert info["backup_commit"]

    assert info["original_branch"]


def test_git_rollback_works_after_memory_reset(tmp_path, monkeypatch):

    _setup_repo(tmp_path, monkeypatch)

    sample = tmp_path / "sample.txt"

    git_create_backup()

    sample.write_text("broken\n", encoding="utf-8")

    project_context._last_backup_branch = None

    project_context._last_backup_commit = None

    project_context._last_original_branch = None

    result = git_rollback()

    assert "Git 回滚完成" in tool_result_message(result)

    assert sample.read_text(encoding="utf-8") == "original\n"


def test_backup_state_ignored_for_different_repo_root(tmp_path, monkeypatch):

    _setup_repo(tmp_path, monkeypatch)

    git_create_backup()

    import config.settings as settings

    other_repo = tmp_path / "other"

    other_repo.mkdir()

    monkeypatch.setattr(settings, "REPO_ROOT", other_repo)

    monkeypatch.setattr(project_context, "REPO_ROOT", other_repo)

    project_context._last_backup_branch = None

    project_context._last_backup_commit = None

    project_context._last_original_branch = None

    assert project_context.get_backup_branch() is None

    assert project_context.get_backup_commit() is None
