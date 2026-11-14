"""Tests for advance_from_outcome TMS-only advancement (PR-M2, PR-M5-b)."""

import pytest

import config.settings as settings
from context.execution_state import get_execution_state, reset_execution_state
from context.mutation_fsm import (
    MutationWorkflowState,
    get_mutation_fsm_context,
    reset_mutation_fsm,
)
from context.tms import MilestoneToken, advance_from_outcome, reset_mutation_state
from context.tms.context import get_shadow
from tools.outcome_schema import tool_success


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, tmp_path):
    import context.project_context as project_context_module

    backup_file = tmp_path / "last_backup.json"
    monkeypatch.setattr(project_context_module, "BACKUP_STATE_FILE", backup_file)
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


def test_advance_proposal_updates_tms_only(monkeypatch):
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", True)

    outcome = tool_success(
        "proposal_generated",
        "修改方案\nscope",
        milestone=MilestoneToken.PROPOSED,
        details={"proposal_digest": "digest1234567890ab"},
    )

    result = advance_from_outcome(
        outcome,
        tool="propose_code_changes",
        args={"task": "x"},
    )

    assert result.advanced is True
    assert result.milestone == MilestoneToken.PROPOSED
    assert result.legacy_mirrored is False
    assert result.tms_updated is True

    shadow = get_shadow()
    assert shadow.workflow.state == MutationWorkflowState.PROPOSED
    assert shadow.workflow.proposal_digest == "digest1234567890ab"
    assert get_execution_state().proposal_digest is None


def test_advance_patch_updates_tms_only(monkeypatch):
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", True)
    monkeypatch.setattr(settings, "MUTATION_FSM_ENABLED", True)

    outcome = tool_success(
        "patch_applied",
        "Patch 应用完成",
        milestone=MilestoneToken.PATCH_APPLIED,
        details={"paths": ["src/a.py"]},
    )

    result = advance_from_outcome(
        outcome,
        tool="apply_patch",
        args={"path": "src/a.py", "new_content": "x\n"},
    )

    assert result.advanced is True
    assert result.legacy_mirrored is False

    shadow = get_shadow()
    assert shadow.workflow.state == MutationWorkflowState.PATCHED
    assert shadow.artifacts.patch_applied_paths == ["src/a.py"]
    assert get_execution_state().patch_applied_paths == []
    assert get_mutation_fsm_context().state == MutationWorkflowState.ANALYZING


def test_advance_reject_does_not_advance():
    from tools.result_schema import tool_reject

    outcome = tool_reject("validation_error", "参数错误: path")

    result = advance_from_outcome(outcome, tool="apply_patch", args={})

    assert result.advanced is False
    assert get_shadow().workflow.state == MutationWorkflowState.ANALYZING


def test_advance_dedup_skip_does_not_advance():
    outcome = tool_success(
        "dedup_skipped",
        "跳过重复 apply_patch",
        milestone=None,
        details={"tool": "apply_patch"},
    )

    result = advance_from_outcome(outcome, tool="apply_patch", args={})

    assert result.advanced is False
