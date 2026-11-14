import json

import pytest

import config.settings as settings
import tools.tool_manager as tool_manager_module
from audit.context import set_task_id
from context.execution_state import (
    BACKUP_SUCCESS_MARKER,
    restore_execution_state,
    update_from_tool_result,
)
from context.project_context import set_backup_info
from context.tms.context import get_shadow
from context.tms.types import BackupRef
from storage.task_store import create_task, mark_task_cancelled
from tools.result_schema import tool_result_message
from tools.tool_manager import run_tool


@pytest.fixture(autouse=True)
def _disable_fsm_for_dedup_isolation_tests(disable_mutation_fsm):
    """Dedup suite isolates resume idempotency; FSM ordering is covered elsewhere."""
    return disable_mutation_fsm


def _enable_dedup(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", True)
    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)
    backup_file = tmp_path / "last_backup.json"
    monkeypatch.setattr(settings, "BACKUP_STATE_FILE", backup_file)
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", tmp_path / "audit.jsonl")

    import context.project_context as project_context_module
    import audit.audit_log as audit_log_module

    monkeypatch.setattr(project_context_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(project_context_module, "BACKUP_STATE_FILE", backup_file)
    monkeypatch.setattr(audit_log_module, "AUDIT_LOG_FILE", tmp_path / "audit.jsonl")
    project_context_module._last_backup_branch = None
    project_context_module._last_backup_commit = None
    project_context_module._last_original_branch = None


def _disable_dedup(monkeypatch):
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", False)


def _patch_tool_function(monkeypatch, tool_name, replacement):
    monkeypatch.setitem(
        tool_manager_module.TOOLS[tool_name],
        "function",
        replacement,
    )


def _seed_backup_state(branch="agent-backup/20260720-125945", commit="c626a6b"):
    set_backup_info(
        backup_branch=branch,
        backup_commit=commit,
        original_branch="master",
    )
    restore_execution_state(
        {
            "proposal_digest": "digest1234567890ab",
            "backup_branch": branch,
            "backup_commit": commit,
            "patch_applied": False,
            "patch_applied_paths": [],
        }
    )
    get_shadow().artifacts.backup = BackupRef(
        backup_branch=branch,
        backup_commit=commit,
        original_branch="master",
    )


def test_run_tool_skips_duplicate_backup(monkeypatch, tmp_path):
    _enable_dedup(monkeypatch, tmp_path)
    set_task_id("dedup-tool-1")

    backup_called = []

    def spy_backup(message=""):
        backup_called.append(message)
        return BACKUP_SUCCESS_MARKER

    _patch_tool_function(monkeypatch, "git_create_backup", spy_backup)
    _seed_backup_state()

    result = run_tool("git_create_backup", {})

    assert backup_called == []
    assert "跳过重复 git_create_backup" in tool_result_message(result)

    audit_lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line) for line in audit_lines]
    dedup_events = [event for event in events if event.get("event") == "execution_state_dedup"]
    assert len(dedup_events) == 1
    assert dedup_events[0]["tool"] == "git_create_backup"
    assert dedup_events[0]["status"] == "skipped"


def test_run_tool_allows_apply_after_backup_only(monkeypatch, tmp_path):
    _enable_dedup(monkeypatch, tmp_path)

    apply_called = []

    def spy_apply(**kwargs):
        apply_called.append(kwargs)
        return "Patch 应用完成\n路径: src/a.py"

    _patch_tool_function(monkeypatch, "apply_patch", spy_apply)
    monkeypatch.setattr(tool_manager_module, "is_tool_confirm_skipped", lambda: True)

    _seed_backup_state()

    result = run_tool(
        "apply_patch",
        {"path": "src/a.py", "new_content": "print('x')\n"},
    )

    assert apply_called
    assert "Patch 应用完成" in tool_result_message(result)
    assert "跳过重复" not in tool_result_message(result)


def test_run_tool_skips_duplicate_apply_patch(monkeypatch, tmp_path):
    _enable_dedup(monkeypatch, tmp_path)

    apply_called = []

    def spy_apply(**kwargs):
        apply_called.append(kwargs)
        return "Patch 应用完成\n路径: src/a.py"

    _patch_tool_function(monkeypatch, "apply_patch", spy_apply)
    monkeypatch.setattr(tool_manager_module, "is_tool_confirm_skipped", lambda: True)

    restore_execution_state(
        {
            "patch_applied": True,
            "patch_applied_paths": ["src/a.py"],
        }
    )
    state = get_shadow()
    state.artifacts.patch_applied = True
    state.artifacts.patch_applied_paths = ["src/a.py"]

    result = run_tool(
        "apply_patch",
        {"path": "src/a.py", "new_content": "print('x')\n"},
    )

    assert apply_called == []
    assert "跳过重复 apply_patch" in tool_result_message(result)


def test_run_tool_allows_apply_for_different_paths(monkeypatch, tmp_path):
    _enable_dedup(monkeypatch, tmp_path)

    apply_called = []

    def spy_apply(**kwargs):
        apply_called.append(kwargs)
        return "Patch 应用完成\n路径: src/other.py"

    _patch_tool_function(monkeypatch, "apply_patch", spy_apply)
    monkeypatch.setattr(tool_manager_module, "is_tool_confirm_skipped", lambda: True)

    restore_execution_state(
        {
            "patch_applied": True,
            "patch_applied_paths": ["src/a.py"],
        }
    )
    state = get_shadow()
    state.artifacts.patch_applied = True
    state.artifacts.patch_applied_paths = ["src/a.py"]

    result = run_tool(
        "apply_patch",
        {"path": "src/other.py", "new_content": "print('y')\n"},
    )

    assert apply_called
    assert "Patch 应用完成" in tool_result_message(result)


def test_new_proposal_resets_backup_dedup(monkeypatch, tmp_path):
    _enable_dedup(monkeypatch, tmp_path)

    backup_called = []

    def spy_backup(message=""):
        backup_called.append(message)
        return BACKUP_SUCCESS_MARKER

    _patch_tool_function(monkeypatch, "git_create_backup", spy_backup)
    _seed_backup_state()

    update_from_tool_result(
        "propose_code_changes",
        {},
        "===== 修改方案 =====\n摘要: different scope",
    )

    result = run_tool("git_create_backup", {})

    assert len(backup_called) == 1
    assert "跳过重复" not in tool_result_message(result)


def test_rebackup_follow_up_clears_backup_dedup(monkeypatch, tmp_path):
    _enable_dedup(monkeypatch, tmp_path)

    backup_called = []

    def spy_backup(message=""):
        backup_called.append(message)
        return BACKUP_SUCCESS_MARKER

    _patch_tool_function(monkeypatch, "git_create_backup", spy_backup)
    _seed_backup_state()

    from context.execution_state import clear_backup_milestones

    clear_backup_milestones()

    run_tool("git_create_backup", {})

    assert len(backup_called) == 1


def test_flag_disabled_does_not_skip_backup(monkeypatch, tmp_path):
    _disable_dedup(monkeypatch)
    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)

    backup_called = []

    def spy_backup(message=""):
        backup_called.append(message)
        return BACKUP_SUCCESS_MARKER

    _patch_tool_function(monkeypatch, "git_create_backup", spy_backup)
    _seed_backup_state()

    result = run_tool("git_create_backup", {})

    assert len(backup_called) == 1
    assert "跳过重复" not in tool_result_message(result)


def test_resume_integration_skips_duplicate_backup(tmp_path, monkeypatch):
    import storage.checkpoint_store as checkpoint_store_module
    import storage.task_store as task_store_module
    from react_agent import react_agent

    db_file = tmp_path / "tasks.db"
    monkeypatch.setattr(settings, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(settings, "CHECKPOINT_ENABLED", True)
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", True)
    monkeypatch.setattr(task_store_module, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(checkpoint_store_module, "TASK_DB_FILE", db_file)
    _enable_dedup(monkeypatch, tmp_path)

    backup_called = []

    def spy_backup(message=""):
        backup_called.append(message)
        return BACKUP_SUCCESS_MARKER

    _patch_tool_function(monkeypatch, "git_create_backup", spy_backup)

    task_id = "dedup-resume-1"
    create_task(task_id, "resume dedup", repo_root=str(tmp_path))
    mark_task_cancelled(task_id)
    _seed_backup_state()

    initial_memory = [
        {"role": "user", "content": "modify sample"},
        {"role": "assistant", "content": '{"action": "git_create_backup", "args": {}}'},
        {"role": "user", "content": "工具执行结果:\nGit 备份完成"},
    ]
    initial_execution_state = {
        "proposal_digest": "digest1234567890ab",
        "backup_branch": "agent-backup/20260720-125945",
        "backup_commit": "c626a6b",
        "patch_applied": False,
        "patch_applied_paths": [],
    }

    sequence = [
        '{"action": "git_create_backup", "args": {}}',
        '{"action": "finish", "answer": "done"}',
    ]
    calls = {"index": 0}

    def sequenced_ask_ai(memory, agent_mode=None):
        idx = calls["index"]
        calls["index"] += 1
        return sequence[min(idx, len(sequence) - 1)]

    monkeypatch.setattr("react_agent.ask_ai", sequenced_ask_ai)

    answer, memory = react_agent(
        "",
        task_id=task_id,
        resume_from_step=1,
        initial_memory=initial_memory,
        initial_execution_state=initial_execution_state,
    )

    assert answer == "done"
    assert backup_called == []
    assert any(
        "跳过重复 git_create_backup" in item.get("content", "")
        for item in memory
        if item.get("role") == "user"
    )


def test_resume_integration_allows_apply_after_backup(tmp_path, monkeypatch):
    import storage.checkpoint_store as checkpoint_store_module
    import storage.task_store as task_store_module
    from react_agent import react_agent

    db_file = tmp_path / "tasks.db"
    monkeypatch.setattr(settings, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(settings, "CHECKPOINT_ENABLED", True)
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", True)
    monkeypatch.setattr(task_store_module, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(checkpoint_store_module, "TASK_DB_FILE", db_file)
    _enable_dedup(monkeypatch, tmp_path)

    apply_called = []

    def spy_apply(**kwargs):
        apply_called.append(kwargs)
        return "Patch 应用完成\n路径: sample.txt"

    _patch_tool_function(monkeypatch, "apply_patch", spy_apply)
    monkeypatch.setattr(tool_manager_module, "is_tool_confirm_skipped", lambda: True)

    task_id = "dedup-resume-2"
    create_task(task_id, "resume apply", repo_root=str(tmp_path))
    mark_task_cancelled(task_id)
    _seed_backup_state()

    initial_memory = [
        {"role": "user", "content": "modify sample.txt"},
        {"role": "assistant", "content": '{"action": "git_create_backup", "args": {}}'},
        {"role": "user", "content": "工具执行结果:\nGit 备份完成"},
    ]
    initial_execution_state = {
        "proposal_digest": "digest1234567890ab",
        "backup_branch": "agent-backup/20260720-125945",
        "backup_commit": "c626a6b",
        "patch_applied": False,
        "patch_applied_paths": [],
    }

    sequence = [
        (
            '{"action": "apply_patch", "args": '
            '{"path": "sample.txt", "new_content": "demo\\n"}}'
        ),
        '{"action": "finish", "answer": "applied"}',
    ]
    calls = {"index": 0}

    def sequenced_ask_ai(memory, agent_mode=None):
        idx = calls["index"]
        calls["index"] += 1
        return sequence[min(idx, len(sequence) - 1)]

    monkeypatch.setattr("react_agent.ask_ai", sequenced_ask_ai)

    answer, _memory = react_agent(
        "",
        task_id=task_id,
        resume_from_step=1,
        initial_memory=initial_memory,
        initial_execution_state=initial_execution_state,
    )

    assert answer == "applied"
    assert len(apply_called) == 1
