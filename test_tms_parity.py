"""Tests for TMS parity checks (PR-M1)."""

import pytest

import config.settings as settings
from context.tms import (
    ArtifactSlice,
    MutationWorkflowState,
    ParityMismatchError,
    TaskMutationState,
    WorkflowSlice,
    build_tms_from_legacy,
    check_tms_parity,
    reset_mutation_state,
    sync_tms_from_legacy,
)
from context.tms.context import get_shadow, set_shadow


@pytest.fixture(autouse=True)
def _reset_tms(monkeypatch, tmp_path):
    import context.project_context as project_context_module
    from context.execution_state import reset_execution_state
    from context.mutation_fsm import reset_mutation_fsm

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


def test_parity_equal_empty():
    left = build_tms_from_legacy()
    right = build_tms_from_legacy()
    assert check_tms_parity(left, right) == []


def test_parity_detects_state_drift():
    canonical = TaskMutationState(
        workflow=WorkflowSlice(state=MutationWorkflowState.BACKED_UP),
    )
    shadow = TaskMutationState(
        workflow=WorkflowSlice(state=MutationWorkflowState.ANALYZING),
    )
    mismatches = check_tms_parity(canonical, shadow)
    assert "workflow.state" in mismatches


def test_parity_paths_order_insensitive():
    canonical = TaskMutationState(
        artifacts=ArtifactSlice(diff_previewed_paths=["b.py", "a.py"]),
    )
    shadow = TaskMutationState(
        artifacts=ArtifactSlice(diff_previewed_paths=["a.py", "b.py"]),
    )
    assert check_tms_parity(canonical, shadow) == []


def test_parity_strict_raises_on_mismatch(monkeypatch):
    monkeypatch.setattr(settings, "PARITY_STRICT", True)
    monkeypatch.setattr(settings, "TMS_ADAPTER_ENABLED", True)

    set_shadow(
        TaskMutationState(
            workflow=WorkflowSlice(state=MutationWorkflowState.PATCHED),
        )
    )

    with pytest.raises(ParityMismatchError):
        sync_tms_from_legacy(task_id="t1", react_step=1)


def test_parity_runtime_legacy_wins(monkeypatch):
    monkeypatch.setattr(settings, "PARITY_STRICT", False)
    monkeypatch.setattr(settings, "TMS_ADAPTER_ENABLED", True)

    set_shadow(
        TaskMutationState(
            workflow=WorkflowSlice(state=MutationWorkflowState.PATCHED),
        )
    )

    result = sync_tms_from_legacy(task_id="t1", react_step=1)
    assert result.ok is False
    assert result.resolution == "legacy_wins"
    assert get_shadow().workflow.state == MutationWorkflowState.ANALYZING
