"""Unit tests for TMS-backed guards (PR-M5-a)."""

import pytest

import config.settings as settings
from context.tms import (
    BackupRef,
    MilestoneToken,
    MutationPath,
    MutationWorkflowState,
    advance_from_outcome,
    check_mutation_allowed,
    reset_mutation_state,
    should_skip_tool_tms,
)
from context.tms.context import get_shadow
from context.project_context import set_backup_info
from tools.outcome_schema import (
    SUCCESS_CODE_BACKUP_CREATED,
    SUCCESS_CODE_DIFF_GENERATED,
    SUCCESS_CODE_PROPOSAL_GENERATED,
    tool_success,
)
from tools.result_schema import REJECT_CODE_MUTATION_FSM_BLOCKED, is_tool_reject


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, tmp_path):
    import context.project_context as project_context_module

    backup_file = tmp_path / "last_backup.json"
    monkeypatch.setattr(project_context_module, "BACKUP_STATE_FILE", backup_file)
    monkeypatch.setattr(settings, "BACKUP_STATE_FILE", backup_file)
    project_context_module._last_backup_branch = None
    project_context_module._last_backup_commit = None
    project_context_module._last_original_branch = None

    reset_mutation_state()
    yield
    reset_mutation_state()


@pytest.fixture
def tms_guards_enabled(monkeypatch):
    monkeypatch.setattr(settings, "TMS_RUNTIME_SOT_ENABLED", True)
    monkeypatch.setattr(settings, "MUTATION_FSM_ENABLED", True)
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", True)


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


def test_guard_routes_to_tms_when_fsm_on_without_runtime_sot_flag(monkeypatch):
    monkeypatch.setattr(settings, "TMS_RUNTIME_SOT_ENABLED", False)
    monkeypatch.setattr(settings, "MUTATION_FSM_ENABLED", True)

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

    reject = check_mutation_allowed(
        "generate_unified_diff",
        {"path": "sample.txt", "new_content": "x"},
        agent_mode="full",
    )

    assert reject is None


def test_dedup_guard_routes_to_tms_when_dedup_on_without_runtime_sot_flag(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "TMS_RUNTIME_SOT_ENABLED", False)
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", True)

    import context.project_context as project_context_module

    backup_file = tmp_path / "last_backup.json"
    monkeypatch.setattr(project_context_module, "BACKUP_STATE_FILE", backup_file)
    monkeypatch.setattr(settings, "BACKUP_STATE_FILE", backup_file)

    branch = "agent-backup/20260720-125945"
    commit = "c626a6b"
    set_backup_info(branch, commit, "main")

    state = get_shadow()
    state.artifacts.backup = BackupRef(
        backup_branch=branch,
        backup_commit=commit,
        original_branch="main",
    )

    from context.tms.guards import should_use_tms_runtime_guards
    from tools.tool_manager import _execution_state_dedup_skip

    assert should_use_tms_runtime_guards() is True
    skip = _execution_state_dedup_skip("git_create_backup", {})
    assert skip is not None
    assert "跳过重复 git_create_backup" in skip


def test_guard_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(settings, "MUTATION_FSM_ENABLED", False)

    reject = check_mutation_allowed(
        "apply_patch",
        {"path": "sample.txt", "new_content": "x"},
        agent_mode="full",
    )

    assert reject is None


def test_guard_blocks_apply_before_backup(tms_guards_enabled):
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

    reject = check_mutation_allowed(
        "apply_patch",
        {"path": "sample.txt", "new_content": "updated\n"},
        agent_mode="full",
    )

    assert reject is not None
    assert is_tool_reject(reject)
    assert reject["code"] == REJECT_CODE_MUTATION_FSM_BLOCKED


def test_guard_allows_diff_first_chain_at_backed_up(tms_guards_enabled):
    _advance_diff_first_backup()

    shadow = get_shadow()
    assert shadow.workflow.state == MutationWorkflowState.BACKED_UP
    assert shadow.workflow.path == MutationPath.DIFF_FIRST

    reject = check_mutation_allowed(
        "apply_patch",
        {"path": "sample.txt", "new_content": "updated\n"},
        agent_mode="full",
    )

    assert reject is None


def test_dedup_skips_duplicate_backup_when_tms_and_global_match(tms_guards_enabled):
    branch = "agent-backup/20260720-125945"
    commit = "c626a6b"
    set_backup_info(branch, commit, "main")

    state = get_shadow()
    state.artifacts.backup = BackupRef(
        backup_branch=branch,
        backup_commit=commit,
        original_branch="main",
    )

    skip = should_skip_tool_tms("git_create_backup", {})

    assert skip is not None
    assert "跳过重复 git_create_backup" in skip


def test_dedup_does_not_skip_when_tms_backup_missing(tms_guards_enabled):
    set_backup_info("agent-backup/x", "deadbeef", "main")

    skip = should_skip_tool_tms("git_create_backup", {})

    assert skip is None


def test_dedup_skips_duplicate_patch_paths(tms_guards_enabled):
    state = get_shadow()
    state.artifacts.patch_applied = True
    state.artifacts.patch_applied_paths = ["sample.txt"]

    skip = should_skip_tool_tms(
        "apply_patch",
        {"path": "sample.txt", "new_content": "updated\n"},
    )

    assert skip is not None
    assert "跳过重复 apply_patch" in skip
