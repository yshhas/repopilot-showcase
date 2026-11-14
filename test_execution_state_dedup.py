import config.settings as settings
from context.execution_state import (
    BACKUP_SUCCESS_MARKER,
    build_resume_hint,
    clear_backup_milestones,
    compute_proposal_digest,
    export_execution_state,
    get_execution_state,
    reset_execution_state,
    restore_execution_state,
    should_skip_tool,
    update_from_tool_result,
    user_requests_rebackup,
)
from context.project_context import set_backup_info


def _enable_dedup(monkeypatch):
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", True)
    reset_execution_state()


def _disable_dedup(monkeypatch):
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", False)
    reset_execution_state()


def test_flag_disabled_export_is_empty_dict(monkeypatch):
    _disable_dedup(monkeypatch)

    update_from_tool_result(
        "git_create_backup",
        {},
        BACKUP_SUCCESS_MARKER,
    )

    assert export_execution_state() == {}


def test_flag_disabled_should_skip_returns_none(monkeypatch):
    _disable_dedup(monkeypatch)

    restore_execution_state(
        {
            "backup_branch": "agent-backup/test",
            "backup_commit": "abc123",
            "patch_applied": False,
        }
    )

    assert should_skip_tool("git_create_backup", {}) is None


def test_export_restore_roundtrip(monkeypatch):
    _enable_dedup(monkeypatch)

    restore_execution_state(
        {
            "proposal_digest": "digest123",
            "backup_branch": "agent-backup/20260720-120000",
            "backup_commit": "deadbeef",
            "diff_previewed_paths": ["a.py", "b.py"],
            "patch_applied": True,
            "patch_applied_paths": ["a.py"],
        }
    )

    exported = export_execution_state()

    assert exported == {
        "proposal_digest": "digest123",
        "backup_branch": "agent-backup/20260720-120000",
        "backup_commit": "deadbeef",
        "diff_previewed_paths": ["a.py", "b.py"],
        "patch_applied": True,
        "patch_applied_paths": ["a.py"],
    }

    reset_execution_state()
    restore_execution_state(exported)
    state = get_execution_state()

    assert state.proposal_digest == "digest123"
    assert state.backup_branch == "agent-backup/20260720-120000"
    assert state.patch_applied is True
    assert state.patch_applied_paths == ["a.py"]


def test_update_proposal_sets_digest_and_resets_milestones(monkeypatch):
    _enable_dedup(monkeypatch)

    proposal_a = "===== 修改方案 =====\n摘要: add logging"
    proposal_b = "===== 修改方案 =====\n摘要: add metrics"

    update_from_tool_result("propose_code_changes", {}, proposal_a)
    state = get_execution_state()
    first_digest = compute_proposal_digest(proposal_a)

    assert state.proposal_digest == first_digest
    assert state.backup_branch is None

    set_backup_info(
        backup_branch="agent-backup/old",
        backup_commit="111",
        original_branch="master",
    )
    update_from_tool_result(
        "git_create_backup",
        {},
        BACKUP_SUCCESS_MARKER,
    )
    state = get_execution_state()
    assert state.backup_branch == "agent-backup/old"

    update_from_tool_result("propose_code_changes", {}, proposal_a)
    state = get_execution_state()
    assert state.proposal_digest == first_digest
    assert state.backup_branch == "agent-backup/old"

    update_from_tool_result("propose_code_changes", {}, proposal_b)
    state = get_execution_state()

    assert state.proposal_digest == compute_proposal_digest(proposal_b)
    assert state.backup_branch is None
    assert state.patch_applied is False
    assert state.patch_applied_paths == []


def test_update_backup_from_successful_tool_result(monkeypatch, tmp_path):
    _enable_dedup(monkeypatch)
    _patch_backup_context(tmp_path, monkeypatch)

    set_backup_info(
        backup_branch="agent-backup/20260720-125945",
        backup_commit="c626a6b",
        original_branch="master",
    )

    update_from_tool_result(
        "git_create_backup",
        {},
        "Git 备份完成\n备份分支: agent-backup/20260720-125945",
    )

    state = get_execution_state()
    assert state.backup_branch == "agent-backup/20260720-125945"
    assert state.backup_commit == "c626a6b"


def test_update_apply_patch_records_paths(monkeypatch):
    _enable_dedup(monkeypatch)

    update_from_tool_result(
        "apply_patch",
        {"path": "src/a.py", "new_content": "x"},
        "Patch 应用完成\n路径: src/a.py",
    )

    state = get_execution_state()
    assert state.patch_applied is True
    assert state.patch_applied_paths == ["src/a.py"]


def test_update_write_repo_file_shares_patch_applied_semantics(monkeypatch):
    _enable_dedup(monkeypatch)

    update_from_tool_result(
        "write_repo_file",
        {"path": "notes.txt", "content": "hello"},
        "文件写入完成\n路径: notes.txt",
    )

    state = get_execution_state()
    assert state.patch_applied is True
    assert state.patch_applied_paths == ["notes.txt"]


def test_should_skip_duplicate_backup_when_persisted_matches(monkeypatch, tmp_path):
    _enable_dedup(monkeypatch)
    _patch_backup_context(tmp_path, monkeypatch)

    set_backup_info(
        backup_branch="agent-backup/20260720-125945",
        backup_commit="c626a6b",
        original_branch="master",
    )

    restore_execution_state(
        {
            "backup_branch": "agent-backup/20260720-125945",
            "backup_commit": "c626a6b",
            "patch_applied": False,
        }
    )

    message = should_skip_tool("git_create_backup", {})

    assert message is not None
    assert "跳过重复 git_create_backup" in message


def test_should_not_skip_backup_when_patch_already_applied(monkeypatch, tmp_path):
    _enable_dedup(monkeypatch)
    _patch_backup_context(tmp_path, monkeypatch)

    set_backup_info(
        backup_branch="agent-backup/20260720-125945",
        backup_commit="c626a6b",
        original_branch="master",
    )

    restore_execution_state(
        {
            "backup_branch": "agent-backup/20260720-125945",
            "backup_commit": "c626a6b",
            "patch_applied": True,
            "patch_applied_paths": ["a.py"],
        }
    )

    assert should_skip_tool("git_create_backup", {}) is None


def test_should_skip_duplicate_apply_patch_for_same_paths(monkeypatch):
    _enable_dedup(monkeypatch)

    restore_execution_state(
        {
            "patch_applied": True,
            "patch_applied_paths": ["src/a.py", "src/b.py"],
        }
    )

    message = should_skip_tool(
        "apply_patch",
        {
            "changes": [
                {"path": "src/b.py", "new_content": "b"},
                {"path": "src/a.py", "new_content": "a"},
            ]
        },
    )

    assert message is not None
    assert "跳过重复 apply_patch" in message


def test_should_not_skip_apply_when_paths_differ(monkeypatch):
    _enable_dedup(monkeypatch)

    restore_execution_state(
        {
            "patch_applied": True,
            "patch_applied_paths": ["src/a.py"],
        }
    )

    assert should_skip_tool(
        "apply_patch",
        {"path": "src/other.py", "new_content": "x"},
    ) is None


def test_build_resume_hint_lists_milestones(monkeypatch):
    _enable_dedup(monkeypatch)

    restore_execution_state(
        {
            "proposal_digest": "abc123",
            "backup_branch": "agent-backup/test",
            "backup_commit": "deadbeef",
            "diff_previewed_paths": ["a.py"],
            "patch_applied": False,
        }
    )

    hint = build_resume_hint()

    assert hint.startswith("[checkpoint]")
    assert "abc123" in hint
    assert "agent-backup/test" in hint
    assert "a.py" in hint
    assert "尚未完成" in hint


def test_build_resume_hint_empty_when_flag_disabled(monkeypatch):
    _disable_dedup(monkeypatch)

    restore_execution_state({"backup_branch": "agent-backup/test"})

    assert build_resume_hint() == ""


def test_user_requests_rebackup_keywords():
    assert user_requests_rebackup("请重新备份后再 apply") is True
    assert user_requests_rebackup("continue please") is False


def test_clear_backup_milestones(monkeypatch):
    _enable_dedup(monkeypatch)

    restore_execution_state(
        {
            "backup_branch": "agent-backup/test",
            "backup_commit": "abc",
        }
    )

    clear_backup_milestones()
    state = get_execution_state()

    assert state.backup_branch is None
    assert state.backup_commit is None


def _patch_backup_context(tmp_path, monkeypatch):
    backup_file = tmp_path / "last_backup.json"

    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(settings, "BACKUP_STATE_FILE", backup_file)

    import context.project_context as project_context_module

    monkeypatch.setattr(project_context_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(project_context_module, "BACKUP_STATE_FILE", backup_file)
    project_context_module._last_backup_branch = None
    project_context_module._last_backup_commit = None
    project_context_module._last_original_branch = None
