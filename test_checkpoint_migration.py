"""Checkpoint v2 migration and hydrate tests (PR-M3)."""


import pytest

import config.settings as settings
import storage.checkpoint_store as checkpoint_store_module
import storage.task_store as task_store_module
from context.execution_state import get_execution_state, reset_execution_state
from context.mutation_fsm import (
    MUTATION_FSM_SNAPSHOT_VERSION,
    MutationPath,
    MutationWorkflowState,
    get_mutation_fsm_context,
    is_mutation_fsm_enabled,
    reset_mutation_fsm,
)
from context.tms import (
    CheckpointHydrateError,
    MutationWorkflowState as TmsWorkflowState,
    apply_checkpoint_mutation_state_to_runtime,
    build_tms_from_legacy,
    export_mutation_state_for_checkpoint,
    hydrate_checkpoint_mutation_state,
    hydrate_mutation_state_from_v1_columns,
    hydrate_mutation_state_v1,
    mirror_tms_to_legacy,
    reset_mutation_state,
)
from context.tms.context import get_shadow
from context.tms.types import MilestoneToken, empty_mutation_state
from storage.checkpoint_store import load_checkpoint, save_checkpoint
from storage.task_store import create_task
from tools.outcome_schema import SUCCESS_CODE_BACKUP_CREATED, tool_success


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


def _patch_db(tmp_path, monkeypatch):
    db_file = tmp_path / "tasks.db"
    monkeypatch.setattr(settings, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(task_store_module, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(checkpoint_store_module, "TASK_DB_FILE", db_file)
    return db_file


def test_export_mutation_state_for_checkpoint_omits_meta():
    outcome = tool_success(
        SUCCESS_CODE_BACKUP_CREATED,
        "Git 备份完成",
        milestone=MilestoneToken.BACKUP_CREATED,
        details={
            "backup_branch": "agent-backup/test",
            "backup_commit": "abc1234",
            "original_branch": "main",
        },
    )
    from context.tms import advance_from_outcome

    advance_from_outcome(outcome, tool="git_create_backup", args={})

    blob = export_mutation_state_for_checkpoint()
    assert blob["schema_version"] == 1
    assert "meta" not in blob
    assert blob["artifacts"]["backup"]["backup_branch"] == "agent-backup/test"


def test_save_checkpoint_mutation_state_v2_flag_on(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "CHECKPOINT_MUTATION_STATE_V2_ENABLED", True)
    create_task("m3-cp-1", "v2 save", repo_root=str(tmp_path))

    mutation_state = {
        "schema_version": 1,
        "workflow": {
            "state": "BACKED_UP",
            "path": "DIFF_FIRST",
            "proposal_digest": "digest1234567890",
        },
        "artifacts": {
            "backup": {
                "backup_branch": "agent-backup/test",
                "backup_commit": "abc1234",
                "original_branch": "main",
            },
            "diff_previewed_paths": ["a.py"],
            "patch_applied": False,
            "patch_applied_paths": [],
        },
        "epoch": 0,
    }

    result = save_checkpoint(
        "m3-cp-1",
        step=2,
        memory=[{"role": "user", "content": "step2"}],
        agent_mode="full",
        repo_root=str(tmp_path),
        mutation_state=mutation_state,
        execution_state={"backup_branch": "agent-backup/test"},
    )

    loaded = load_checkpoint(result.checkpoint_id)
    assert loaded is not None
    assert loaded.mutation_state == mutation_state


def test_save_checkpoint_v2_flag_off_omits_mutation_state(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "CHECKPOINT_MUTATION_STATE_V2_ENABLED", False)
    create_task("m3-cp-2", "v1 save", repo_root=str(tmp_path))

    result = save_checkpoint(
        "m3-cp-2",
        step=1,
        memory=[{"role": "user", "content": "x"}],
        agent_mode="full",
        repo_root=str(tmp_path),
        mutation_state={"schema_version": 1, "workflow": {}, "artifacts": {}, "epoch": 0},
    )

    loaded = load_checkpoint(result.checkpoint_id)
    assert loaded is not None
    assert loaded.mutation_state == {
        "schema_version": 1,
        "workflow": {},
        "artifacts": {},
        "epoch": 0,
    }


def test_save_checkpoint_strips_v1_when_mutation_state_present(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    create_task("m5e-cp-1", "v2 strips v1", repo_root=str(tmp_path))

    mutation_state = {
        "schema_version": 1,
        "workflow": {"state": "PROPOSED", "path": "NONE", "proposal_digest": "d" * 16},
        "artifacts": {},
        "epoch": 0,
    }

    result = save_checkpoint(
        "m5e-cp-1",
        step=1,
        memory=[{"role": "user", "content": "x"}],
        agent_mode="full",
        repo_root=str(tmp_path),
        mutation_state=mutation_state,
        execution_state={"proposal_digest": "d" * 16},
        mutation_fsm={"state": "PROPOSED"},
    )

    loaded = load_checkpoint(result.checkpoint_id)
    assert loaded is not None
    assert loaded.mutation_state == mutation_state
    assert loaded.execution_state is None
    assert loaded.mutation_fsm is None


def test_hydrate_v2_blob_priority():
    v2 = {
        "schema_version": 1,
        "workflow": {
            "state": "BACKED_UP",
            "path": "DIFF_FIRST",
            "proposal_digest": "abc",
        },
        "artifacts": {
            "backup": None,
            "diff_previewed_paths": ["x.py"],
            "patch_applied": False,
            "patch_applied_paths": [],
        },
        "epoch": 0,
    }
    v1_exec = {"proposal_digest": "other", "patch_applied": True}

    state, diag = hydrate_checkpoint_mutation_state(
        mutation_state=v2,
        execution_state=v1_exec,
        mutation_fsm=None,
        task_id="t1",
    )

    assert diag.source == "v2_blob"
    assert state.workflow.state == TmsWorkflowState.BACKED_UP
    assert state.artifacts.diff_previewed_paths == ["x.py"]
    assert diag.v1_v2_divergence is True


def test_hydrate_v1_merge_when_no_v2():
    fsm = {
        "version": MUTATION_FSM_SNAPSHOT_VERSION,
        "state": MutationWorkflowState.BACKED_UP.value,
        "mutation_path": MutationPath.DIFF_FIRST.value,
        "proposal_digest": "abc123",
    }
    execution_state = {
        "proposal_digest": "abc123",
        "diff_previewed_paths": ["sample.txt"],
        "backup_branch": "agent-backup/test",
        "backup_commit": "deadbeef",
        "patch_applied": False,
    }

    state, diag = hydrate_checkpoint_mutation_state(
        mutation_state=None,
        execution_state=execution_state,
        mutation_fsm=fsm,
    )

    assert diag.source == "v1_merge"
    assert state.workflow.state == TmsWorkflowState.BACKED_UP
    assert state.artifacts.backup is not None
    assert state.artifacts.backup.backup_branch == "agent-backup/test"


def test_hydrate_empty_when_no_mutation_columns():
    state, diag = hydrate_checkpoint_mutation_state(
        mutation_state=None,
        execution_state=None,
        mutation_fsm=None,
    )

    assert diag.source == "empty"
    assert state.workflow.state == TmsWorkflowState.ANALYZING


def test_hydrate_corrupted_v2_enters_safe_diagnostics():
    state, diag = hydrate_checkpoint_mutation_state(
        mutation_state={"schema_version": 99, "workflow": {}, "artifacts": {}, "epoch": 0},
        execution_state=None,
        mutation_fsm=None,
    )

    assert diag.corrupted is True
    assert state.workflow.state == TmsWorkflowState.ANALYZING


def test_hydrate_mutation_state_v1_strict_raises():
    with pytest.raises(CheckpointHydrateError):
        hydrate_mutation_state_v1(
            {"schema_version": 99, "workflow": {}, "artifacts": {}, "epoch": 0},
            strict=True,
        )


def test_apply_checkpoint_sets_shadow_without_legacy_mirror(monkeypatch):
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", True)
    monkeypatch.setattr(settings, "MUTATION_FSM_ENABLED", True)

    merged, _ = hydrate_mutation_state_from_v1_columns(
        mutation_fsm_json={
            "version": MUTATION_FSM_SNAPSHOT_VERSION,
            "state": MutationWorkflowState.PROPOSED.value,
            "mutation_path": MutationPath.NONE.value,
            "proposal_digest": "digest1234567890",
        },
        execution_state_json={
            "proposal_digest": "digest1234567890",
            "patch_applied": False,
        },
    )

    reset_execution_state()
    reset_mutation_fsm()

    apply_checkpoint_mutation_state_to_runtime(merged, task_id="rt-1", react_step=3)

    shadow = get_shadow()
    assert shadow.workflow.state == merged.workflow.state
    assert shadow.workflow.proposal_digest == merged.workflow.proposal_digest
    assert get_execution_state().proposal_digest is None
    assert get_mutation_fsm_context().state == MutationWorkflowState.ANALYZING

    mirror_tms_to_legacy(merged)
    rebuilt = build_tms_from_legacy()
    assert rebuilt.workflow.state == merged.workflow.state
    assert rebuilt.workflow.proposal_digest == merged.workflow.proposal_digest


def test_mirror_tms_to_legacy_populates_execution_state(monkeypatch):
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", True)
    monkeypatch.setattr(settings, "MUTATION_FSM_ENABLED", True)

    state = empty_mutation_state()
    state.workflow.state = TmsWorkflowState.BACKED_UP
    state.workflow.path = MutationPath.DIFF_FIRST
    state.workflow.proposal_digest = "abc123"
    state.artifacts.diff_previewed_paths = ["file.py"]

    mirror_tms_to_legacy(state)

    es = get_execution_state()
    assert es.proposal_digest == "abc123"
    assert es.diff_previewed_paths == ["file.py"]

    if is_mutation_fsm_enabled():
        ctx = get_mutation_fsm_context()
        assert ctx.state == MutationWorkflowState.BACKED_UP


def test_v1_merge_derive_mismatch():
    fsm = {
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

    _, derive_mismatch = hydrate_mutation_state_from_v1_columns(
        mutation_fsm_json=fsm,
        execution_state_json=execution_state,
    )

    assert derive_mismatch is True
