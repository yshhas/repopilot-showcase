import json

import pytest

import config.settings as settings
import storage.checkpoint_store as checkpoint_store_module
import storage.task_store as task_store_module
import tools.tool_manager as tool_manager_module
from audit.context import reset_agent_mode, set_agent_mode
from config.agent_mode import AGENT_MODE_FULL
from context.mutation_fsm import (
    MUTATION_FSM_SNAPSHOT_VERSION,
    MutationPath,
    MutationWorkflowState,
    advance_mutation_fsm_on_success,
    check_mutation_fsm_allowed,
    derive_mutation_fsm_from_execution_state,
    export_mutation_fsm_snapshot,
    get_mutation_fsm_context,
    hydrate_mutation_fsm_from_checkpoint,
    reset_mutation_fsm,
    restore_mutation_fsm,
)
from react_agent import react_agent
from storage.checkpoint_store import get_latest_checkpoint, save_checkpoint
from storage.task_store import create_task, mark_task_cancelled
from tools.tool_manager import run_tool


@pytest.fixture(autouse=True)
def _reset_runtime_state():
    from context.execution_state import reset_execution_state
    from context.tms import reset_mutation_state

    reset_execution_state()
    reset_mutation_fsm()
    reset_mutation_state()
    yield
    reset_execution_state()
    reset_mutation_fsm()
    reset_mutation_state()


@pytest.fixture
def fsm_enabled(monkeypatch):
    _enable_fsm(monkeypatch)
    yield
    reset_mutation_fsm()


def _load_audit_events(path):
    if not path.exists():
        return []

    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def _patch_agent_dbs(tmp_path, monkeypatch):
    db_file = tmp_path / "tasks.db"
    audit_file = tmp_path / "audit.jsonl"
    monkeypatch.setattr(settings, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", audit_file)
    monkeypatch.setattr(settings, "CHECKPOINT_ENABLED", True)
    monkeypatch.setattr(task_store_module, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(checkpoint_store_module, "TASK_DB_FILE", db_file)

    import audit.audit_log as audit_log_module

    monkeypatch.setattr(audit_log_module, "AUDIT_LOG_FILE", audit_file)
    return audit_file


PROPOSAL_TEXT = "修改方案\nsummary: test"
DIFF_TEXT = "Unified diff preview\n--- a/sample.txt"
BACKUP_TEXT = "Git 备份完成\nbranch: agent-backup/test"
PATCH_TEXT = "Patch 应用完成\npath: sample.txt"


def _patch_db(tmp_path, monkeypatch):
    return _patch_agent_dbs(tmp_path, monkeypatch)


def _enable_fsm(monkeypatch):
    monkeypatch.setattr(settings, "MUTATION_FSM_ENABLED", True)
    reset_mutation_fsm()


def _disable_fsm(monkeypatch):
    monkeypatch.setattr(settings, "MUTATION_FSM_ENABLED", False)
    reset_mutation_fsm()


def _advance_diff_first_backup():
    advance_mutation_fsm_on_success("propose_code_changes", {}, PROPOSAL_TEXT)
    advance_mutation_fsm_on_success(
        "generate_unified_diff",
        {"path": "sample.txt", "new_content": "updated\n"},
        DIFF_TEXT,
    )
    advance_mutation_fsm_on_success("git_create_backup", {}, BACKUP_TEXT)


def test_checkpoint_persists_mutation_fsm_when_enabled(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    _enable_fsm(monkeypatch)
    create_task("fsm-cp-1", "fsm checkpoint", repo_root=str(tmp_path))

    _advance_diff_first_backup()
    snapshot = export_mutation_fsm_snapshot()

    result = save_checkpoint(
        "fsm-cp-1",
        step=2,
        memory=[{"role": "user", "content": "step2"}],
        agent_mode="full",
        repo_root=str(tmp_path),
        mutation_fsm=snapshot,
    )

    assert result.ok is True
    loaded = get_latest_checkpoint("fsm-cp-1")
    assert loaded is not None
    assert loaded.mutation_fsm == snapshot
    assert loaded.mutation_fsm["version"] == MUTATION_FSM_SNAPSHOT_VERSION
    assert loaded.mutation_fsm["state"] == MutationWorkflowState.BACKED_UP.value
    assert loaded.mutation_fsm["mutation_path"] == MutationPath.DIFF_FIRST.value


def test_checkpoint_omits_mutation_fsm_when_disabled(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    _disable_fsm(monkeypatch)
    create_task("fsm-cp-2", "fsm off", repo_root=str(tmp_path))

    result = save_checkpoint(
        "fsm-cp-2",
        step=1,
        memory=[{"role": "user", "content": "step1"}],
        agent_mode="full",
        repo_root=str(tmp_path),
        mutation_fsm=None,
    )

    loaded = get_latest_checkpoint("fsm-cp-2")
    assert result.ok is True
    assert loaded is not None
    assert loaded.mutation_fsm is None


def test_restore_rejects_invalid_snapshot_version(fsm_enabled):
    restore_mutation_fsm(
        {
            "version": 99,
            "state": MutationWorkflowState.BACKED_UP.value,
            "mutation_path": MutationPath.DIFF_FIRST.value,
        }
    )

    ctx = get_mutation_fsm_context()
    assert ctx.state == MutationWorkflowState.ANALYZING
    assert ctx.mutation_path == MutationPath.NONE


def test_hydrate_uses_snapshot_over_derive(fsm_enabled):
    snapshot = {
        "version": MUTATION_FSM_SNAPSHOT_VERSION,
        "state": MutationWorkflowState.BACKED_UP.value,
        "mutation_path": MutationPath.DIFF_FIRST.value,
        "proposal_digest": "abc123",
    }
    execution_state = {
        "proposal_digest": "abc123",
        "diff_previewed_paths": ["sample.txt"],
        "backup_branch": "agent-backup/test",
        "patch_applied": False,
    }

    source, mismatch = hydrate_mutation_fsm_from_checkpoint(snapshot, execution_state)

    ctx = get_mutation_fsm_context()
    assert source == "snapshot"
    assert mismatch is False
    assert ctx.state == MutationWorkflowState.BACKED_UP
    assert ctx.mutation_path == MutationPath.DIFF_FIRST
    assert check_mutation_fsm_allowed(
        "apply_patch",
        {"path": "sample.txt", "new_content": "updated\n"},
        agent_mode=AGENT_MODE_FULL,
    ) is None


def test_hydrate_derives_from_execution_state_when_no_snapshot(fsm_enabled):
    execution_state = {
        "proposal_digest": "deadbeef",
        "diff_previewed_paths": ["sample.txt"],
        "backup_branch": "agent-backup/test",
        "patch_applied": False,
    }

    source, mismatch = hydrate_mutation_fsm_from_checkpoint(None, execution_state)

    ctx = get_mutation_fsm_context()
    assert source == "derived"
    assert mismatch is False
    assert ctx.state == MutationWorkflowState.BACKED_UP
    assert ctx.mutation_path == MutationPath.DIFF_FIRST


def test_hydrate_snapshot_mismatch_with_derive(fsm_enabled):
    snapshot = {
        "version": MUTATION_FSM_SNAPSHOT_VERSION,
        "state": MutationWorkflowState.BACKED_UP.value,
        "mutation_path": MutationPath.WRITE_FALLBACK.value,
        "proposal_digest": "abc123",
    }
    execution_state = {
        "proposal_digest": "abc123",
        "diff_previewed_paths": ["sample.txt"],
        "backup_branch": "agent-backup/test",
        "patch_applied": False,
    }

    source, mismatch = hydrate_mutation_fsm_from_checkpoint(snapshot, execution_state)

    ctx = get_mutation_fsm_context()
    assert source == "snapshot"
    assert mismatch is True
    assert ctx.mutation_path == MutationPath.WRITE_FALLBACK


def test_derive_write_fallback_path_from_execution_state(fsm_enabled):
    execution_state = {
        "proposal_digest": "abc123",
        "backup_branch": "agent-backup/test",
        "patch_applied": False,
    }

    derived = derive_mutation_fsm_from_execution_state(execution_state)

    assert derived is not None
    assert derived["state"] == MutationWorkflowState.BACKED_UP.value
    assert derived["mutation_path"] == MutationPath.WRITE_FALLBACK.value


def test_fsm_blocked_writes_audit_event(tmp_path, monkeypatch):
    audit_file = _patch_db(tmp_path, monkeypatch)
    _enable_fsm(monkeypatch)
    mode_token = set_agent_mode(AGENT_MODE_FULL)

    result = run_tool(
        "apply_patch",
        {"path": "sample.txt", "new_content": "updated\n"},
    )

    reset_agent_mode(mode_token)

    from tools.result_schema import tool_result_message

    text = tool_result_message(result)
    assert "mutation_fsm_blocked" in text or text.startswith("Mutation workflow blocked:")

    events = _load_audit_events(audit_file)
    blocked = [event for event in events if event.get("event") == "mutation_fsm_blocked"]
    assert len(blocked) == 1
    assert blocked[0]["tool"] == "apply_patch"
    assert blocked[0]["code"] == "mutation_fsm_blocked"
    assert blocked[0]["current_state"] == MutationWorkflowState.ANALYZING.value


def test_fsm_blocked_audit_absent_when_flag_off(tmp_path, monkeypatch):
    audit_file = _patch_db(tmp_path, monkeypatch)
    _disable_fsm(monkeypatch)
    mode_token = set_agent_mode(AGENT_MODE_FULL)
    monkeypatch.setattr(tool_manager_module, "is_tool_confirm_skipped", lambda: True)

    run_tool(
        "apply_patch",
        {"path": "sample.txt", "new_content": "updated\n"},
    )

    reset_agent_mode(mode_token)

    events = _load_audit_events(audit_file)
    assert not any(event.get("event") == "mutation_fsm_blocked" for event in events)


def test_react_agent_resume_restores_fsm_from_checkpoint(tmp_path, monkeypatch):
    _patch_agent_dbs(tmp_path, monkeypatch)
    _enable_fsm(monkeypatch)
    task_id = "fsm_resume_cp"

    _advance_diff_first_backup()
    snapshot = export_mutation_fsm_snapshot()
    execution_state = {
        "proposal_digest": "abc1234567890abcd",
        "diff_previewed_paths": ["sample.txt"],
        "backup_branch": "agent-backup/test",
        "patch_applied": False,
        "patch_applied_paths": [],
    }

    create_task(task_id, "resume fsm", repo_root=str(tmp_path))
    mark_task_cancelled(task_id)

    save_checkpoint(
        task_id,
        step=3,
        memory=[{"role": "user", "content": "paused"}],
        agent_mode=AGENT_MODE_FULL,
        repo_root=str(tmp_path),
        mutation_fsm=snapshot,
        execution_state=execution_state,
    )

    restored_steps = []

    def capture_log(step, **fields):
        if step == "mutation_state_restored":
            restored_steps.append(fields)

    monkeypatch.setattr("react_agent.log_react_step", capture_log)

    def fake_ask_ai(memory, agent_mode=None):
        return '{"action": "finish", "answer": "resumed"}'

    monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)

    answer, _memory = react_agent(
        "",
        task_id=task_id,
        agent_mode=AGENT_MODE_FULL,
        resume_from_step=3,
        initial_memory=[{"role": "user", "content": "paused"}],
        initial_mutation_fsm=snapshot,
        initial_execution_state=execution_state,
    )

    assert answer == "resumed"

    from context.tms.context import get_shadow

    shadow = get_shadow()
    assert shadow.workflow.state == MutationWorkflowState.BACKED_UP
    assert len(restored_steps) == 1
    assert restored_steps[0]["hydrate_source"] == "v1_merge"
    assert restored_steps[0]["workflow_state"] == MutationWorkflowState.BACKED_UP.value
    assert restored_steps[0]["derive_mismatch"] is False
