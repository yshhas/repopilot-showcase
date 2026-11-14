"""M5 regression tests — TMS runtime SoT guards and dedup (PR-M5-a)."""

import json

import pytest

import config.settings as settings
import tools.tool_manager as tool_manager_module
from audit.context import set_task_id
from context.execution_state import get_execution_state
from context.mutation_fsm import (
    MutationWorkflowState,
    get_mutation_fsm_context,
    is_fsm_reject_result,
)
from context.project_context import set_backup_info
from context.tms import (
    MilestoneToken,
    MutationPath,
    advance_from_outcome,
    apply_checkpoint_mutation_state_to_runtime,
    hydrate_checkpoint_mutation_state,
    reset_mutation_state,
)
from context.tms.context import get_shadow
from tools.outcome_schema import (
    SUCCESS_CODE_BACKUP_CREATED,
    SUCCESS_CODE_DIFF_GENERATED,
    SUCCESS_CODE_PATCH_APPLIED,
    SUCCESS_CODE_PROPOSAL_GENERATED,
    tool_success,
)
from tools.result_schema import tool_result_message
from tools.tool_manager import run_tool


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, tmp_path):
    import context.project_context as project_context_module
    from context.execution_state import reset_execution_state
    from context.mutation_fsm import reset_mutation_fsm

    backup_file = tmp_path / "last_backup.json"
    audit_file = tmp_path / "audit.jsonl"
    monkeypatch.setattr(project_context_module, "BACKUP_STATE_FILE", backup_file)
    monkeypatch.setattr(settings, "BACKUP_STATE_FILE", backup_file)
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", audit_file)
    project_context_module._last_backup_branch = None
    project_context_module._last_backup_commit = None
    project_context_module._last_original_branch = None

    reset_execution_state()
    reset_mutation_fsm()
    reset_mutation_state()
    yield
    reset_execution_state()
    reset_mutation_fsm()
    reset_mutation_state()


@pytest.fixture
def m5_enabled(monkeypatch):
    monkeypatch.setattr(settings, "TMS_RUNTIME_SOT_ENABLED", True)
    monkeypatch.setattr(settings, "MUTATION_FSM_ENABLED", True)
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", True)


def _patch_confirm_skip(monkeypatch):
    monkeypatch.setattr(tool_manager_module, "is_tool_confirm_skipped", lambda: True)


def _advance_diff_first_backup():
    advance_from_outcome(
        tool_success(
            SUCCESS_CODE_PROPOSAL_GENERATED,
            "修改方案",
            milestone=MilestoneToken.PROPOSED,
            details={"proposal_digest": "digest1234567890ab"},
        ),
        tool="propose_code_changes",
        args={"task": "x"},
    )
    advance_from_outcome(
        tool_success(
            SUCCESS_CODE_DIFF_GENERATED,
            "Unified diff preview",
            milestone=MilestoneToken.DIFF_GENERATED,
            details={"paths": ["sample.txt"]},
        ),
        tool="generate_unified_diff",
        args={"path": "sample.txt", "new_content": "updated\n"},
    )
    advance_from_outcome(
        tool_success(
            SUCCESS_CODE_BACKUP_CREATED,
            "Git 备份完成",
            milestone=MilestoneToken.BACKUP_CREATED,
            details={
                "backup_branch": "agent-backup/test",
                "backup_commit": "abc1234",
                "original_branch": "main",
            },
        ),
        tool="git_create_backup",
        args={},
    )


def test_m5_run_tool_blocks_apply_before_backup(m5_enabled, monkeypatch):
    _patch_confirm_skip(monkeypatch)

    advance_from_outcome(
        tool_success(
            SUCCESS_CODE_PROPOSAL_GENERATED,
            "修改方案",
            milestone=MilestoneToken.PROPOSED,
            details={"proposal_digest": "digest1234567890ab"},
        ),
        tool="propose_code_changes",
        args={"task": "x"},
    )

    called = {"count": 0}

    def spy_apply(**kwargs):
        called["count"] += 1
        return "Patch 应用完成"

    monkeypatch.setitem(
        tool_manager_module.TOOLS["apply_patch"],
        "function",
        spy_apply,
    )

    result = run_tool(
        "apply_patch",
        {"path": "sample.txt", "new_content": "updated\n"},
    )

    assert called["count"] == 0
    assert is_fsm_reject_result(result)


def test_m5_structured_advance_enables_apply_guard(m5_enabled, monkeypatch):
    _patch_confirm_skip(monkeypatch)
    _advance_diff_first_backup()

    called = {"count": 0}

    def spy_apply(**kwargs):
        called["count"] += 1
        return tool_success(
            SUCCESS_CODE_PATCH_APPLIED,
            "Patch 应用完成",
            milestone=MilestoneToken.PATCH_APPLIED,
            details={"paths": ["sample.txt"]},
        )

    monkeypatch.setitem(
        tool_manager_module.TOOLS["apply_patch"],
        "function",
        spy_apply,
    )

    result = run_tool(
        "apply_patch",
        {"path": "sample.txt", "new_content": "updated\n"},
    )

    assert called["count"] == 1
    assert "Patch 应用完成" in tool_result_message(result)

    shadow = get_shadow()
    assert shadow.workflow.state == MutationWorkflowState.BACKED_UP
    assert shadow.workflow.path == MutationPath.DIFF_FIRST


def test_m5_run_tool_skips_duplicate_backup_via_tms(m5_enabled, monkeypatch, tmp_path):
    _patch_confirm_skip(monkeypatch)
    set_task_id("m5-dedup-1")

    branch = "agent-backup/20260720-125945"
    commit = "c626a6b"
    set_backup_info(branch, commit, "main")

    execution_state_json = {
        "proposal_digest": "digest1234567890ab",
        "backup_branch": branch,
        "backup_commit": commit,
        "patch_applied": False,
        "patch_applied_paths": [],
    }
    state, diagnostics = hydrate_checkpoint_mutation_state(
        mutation_state=None,
        execution_state=execution_state_json,
        mutation_fsm=None,
    )
    assert diagnostics.source == "v1_merge"
    apply_checkpoint_mutation_state_to_runtime(state)

    backup_called = []

    def spy_backup(message=""):
        backup_called.append(message)
        return "Git 备份完成"

    monkeypatch.setitem(
        tool_manager_module.TOOLS["git_create_backup"],
        "function",
        spy_backup,
    )

    result = run_tool("git_create_backup", {})

    assert backup_called == []
    assert "跳过重复 git_create_backup" in tool_result_message(result)


def test_m5_v09_checkpoint_hydrate_populates_tms_for_guard(m5_enabled, monkeypatch):
    _patch_confirm_skip(monkeypatch)

    execution_state_json = {
        "proposal_digest": "digest1234567890ab",
        "backup_branch": "agent-backup/resume",
        "backup_commit": "feedface",
        "diff_previewed_paths": ["sample.txt"],
        "patch_applied": False,
        "patch_applied_paths": [],
    }
    mutation_fsm_json = {
        "version": 1,
        "state": "BACKED_UP",
        "mutation_path": "DIFF_FIRST",
        "proposal_digest": "digest1234567890ab",
    }

    state, diagnostics = hydrate_checkpoint_mutation_state(
        mutation_state=None,
        execution_state=execution_state_json,
        mutation_fsm=mutation_fsm_json,
    )
    assert diagnostics.source == "v1_merge"
    apply_checkpoint_mutation_state_to_runtime(state)

    shadow = get_shadow()
    assert shadow.workflow.state == MutationWorkflowState.BACKED_UP
    assert shadow.workflow.path == MutationPath.DIFF_FIRST
    assert shadow.artifacts.backup is not None
    assert shadow.artifacts.backup.backup_branch == "agent-backup/resume"

    called = {"count": 0}

    def spy_apply(**kwargs):
        called["count"] += 1
        return tool_success(
            SUCCESS_CODE_PATCH_APPLIED,
            "Patch 应用完成",
            milestone=MilestoneToken.PATCH_APPLIED,
            details={"paths": ["sample.txt"]},
        )

    monkeypatch.setitem(
        tool_manager_module.TOOLS["apply_patch"],
        "function",
        spy_apply,
    )

    result = run_tool(
        "apply_patch",
        {"path": "sample.txt", "new_content": "updated\n"},
    )

    assert called["count"] == 1
    assert "Patch 应用完成" in tool_result_message(result)


def test_m5_empty_tms_allows_fresh_backup(m5_enabled, monkeypatch):
    _patch_confirm_skip(monkeypatch)

    called = {"count": 0}

    def spy_backup(message=""):
        called["count"] += 1
        return tool_success(
            SUCCESS_CODE_BACKUP_CREATED,
            "Git 备份完成",
            milestone=MilestoneToken.BACKUP_CREATED,
            details={
                "backup_branch": "agent-backup/fresh",
                "backup_commit": "1111111",
                "original_branch": "main",
            },
        )

    monkeypatch.setitem(
        tool_manager_module.TOOLS["git_create_backup"],
        "function",
        spy_backup,
    )

    advance_from_outcome(
        tool_success(
            SUCCESS_CODE_PROPOSAL_GENERATED,
            "修改方案",
            milestone=MilestoneToken.PROPOSED,
            details={"proposal_digest": "digest1234567890ab"},
        ),
        tool="propose_code_changes",
        args={"task": "x"},
    )

    result = run_tool("git_create_backup", {})

    assert called["count"] == 1
    assert "Git 备份完成" in tool_result_message(result)


def test_m5_advance_does_not_mirror_legacy_state(m5_enabled):
    result = advance_from_outcome(
        tool_success(
            SUCCESS_CODE_PROPOSAL_GENERATED,
            "修改方案",
            milestone=MilestoneToken.PROPOSED,
            details={"proposal_digest": "digest1234567890ab"},
        ),
        tool="propose_code_changes",
        args={"task": "x"},
    )

    assert result.advanced is True
    assert result.legacy_mirrored is False
    assert get_execution_state().proposal_digest is None
    assert get_mutation_fsm_context().state == MutationWorkflowState.ANALYZING


def test_m5_guard_audit_records_tms_source(m5_enabled, monkeypatch, tmp_path):
    _patch_confirm_skip(monkeypatch)
    import audit.audit_log as audit_log_module

    audit_file = tmp_path / "audit_guard.jsonl"
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", audit_file)
    monkeypatch.setattr(audit_log_module, "AUDIT_LOG_FILE", audit_file)

    run_tool(
        "apply_patch",
        {"path": "sample.txt", "new_content": "updated\n"},
    )

    events = [
        json.loads(line)
        for line in audit_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    blocked = [event for event in events if event.get("event") == "mutation_fsm_blocked"]
    assert len(blocked) == 1
    assert blocked[0].get("guard_source") == "tms"
