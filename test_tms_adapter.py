"""Tests for TaskMutationState adapter mapping (PR-M1)."""

import pytest

import config.settings as settings
from context.execution_state import (
    get_execution_state,
    reset_execution_state,
    update_from_tool_result,
)
from context.mutation_fsm import (
    get_mutation_fsm_context,
    reset_mutation_fsm,
)
from context.project_context import set_backup_info
from context.tms import (
    TMS_SCHEMA_VERSION,
    MilestoneToken,
    MutationPath,
    MutationWorkflowState,
    build_tms_from_legacy,
    export_mutation_state_v1,
    hydrate_mutation_state_v1,
    parse_milestone_token,
    reset_mutation_state,
    sync_tms_from_legacy,
)
from context.tms.context import get_shadow


@pytest.fixture(autouse=True)
def _reset_legacy_and_tms(monkeypatch, tmp_path):
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
    project_context_module._last_backup_branch = None
    project_context_module._last_backup_commit = None
    project_context_module._last_original_branch = None


def test_empty_legacy_maps_to_analyzing():
    tms = build_tms_from_legacy()
    assert tms.workflow.state == MutationWorkflowState.ANALYZING
    assert tms.workflow.path == MutationPath.NONE
    assert tms.artifacts.backup is None
    assert tms.artifacts.patch_applied is False


def test_proposal_digest_from_execution_state(monkeypatch):
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", True)
    reset_execution_state()
    update_from_tool_result(
        "propose_code_changes",
        {"task": "x"},
        "===== 修改方案 =====\ncontent",
    )

    tms = build_tms_from_legacy()
    assert tms.workflow.proposal_digest is not None


def test_backup_from_execution_state_and_project_context(monkeypatch):
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", True)
    set_backup_info("agent-backup/test", "abc1234", "main")
    reset_execution_state()
    update_from_tool_result(
        "git_create_backup",
        {},
        "Git 备份完成\nbranch",
    )

    tms = build_tms_from_legacy()
    assert tms.artifacts.backup is not None
    assert tms.artifacts.backup.backup_branch == "agent-backup/test"
    assert tms.artifacts.backup.backup_commit == "abc1234"


def test_fsm_enabled_export_preferred(monkeypatch):
    monkeypatch.setattr(settings, "MUTATION_FSM_ENABLED", True)
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", True)
    reset_mutation_fsm()
    reset_execution_state()

    update_from_tool_result(
        "propose_code_changes",
        {"task": "x"},
        "===== 修改方案 =====\ncontent",
    )

    ctx = get_mutation_fsm_context()
    ctx.state = MutationWorkflowState.PROPOSED
    ctx.mutation_path = MutationPath.NONE
    ctx.proposal_digest = get_execution_state().proposal_digest

    tms = build_tms_from_legacy()
    assert tms.workflow.state == MutationWorkflowState.PROPOSED


def test_export_import_round_trip():
    set_backup_info("agent-backup/r1", "deadbeef", "main")
    reset_execution_state()
    update_from_tool_result(
        "generate_unified_diff",
        {"path": "a.py", "new_content": "x\n"},
        "unified diff preview\n",
    )

    canonical = build_tms_from_legacy()
    blob = export_mutation_state_v1(canonical, task_id="t1", react_step=3)
    restored = hydrate_mutation_state_v1(blob)

    assert restored.workflow.state == canonical.workflow.state
    assert restored.artifacts.diff_previewed_paths == canonical.artifacts.diff_previewed_paths
    assert blob["schema_version"] == TMS_SCHEMA_VERSION


def test_hydrate_ignores_unknown_fields():
    blob = {
        "schema_version": 1,
        "workflow": {"state": "PROPOSED", "path": "NONE", "proposal_digest": "abc"},
        "artifacts": {
            "backup": None,
            "diff_previewed_paths": [],
            "patch_applied": False,
            "patch_applied_paths": [],
            "future_field": "ignored",
        },
        "epoch": 0,
        "unknown_top_level": True,
    }
    restored = hydrate_mutation_state_v1(blob)
    assert restored.workflow.state == MutationWorkflowState.PROPOSED


def test_hydrate_unsupported_schema_version_returns_empty():
    blob = {"schema_version": 99, "workflow": {"state": "PATCHED"}}
    restored = hydrate_mutation_state_v1(blob)
    assert restored.workflow.state == MutationWorkflowState.ANALYZING


def test_milestone_token_closed_enum():
    assert parse_milestone_token("BACKUP_CREATED") == MilestoneToken.BACKUP_CREATED
    assert parse_milestone_token("DIFF_GENERATED") == MilestoneToken.DIFF_GENERATED
    assert parse_milestone_token("not-a-token") is None


def test_sync_tms_from_legacy_updates_shadow():
    set_backup_info("agent-backup/sync", "1111111", "main")
    reset_execution_state()
    update_from_tool_result(
        "git_create_backup",
        {},
        "Git 备份完成",
    )

    result = sync_tms_from_legacy(task_id="task1", react_step=2)
    assert result.ok is True

    shadow = get_shadow()
    assert shadow.artifacts.backup is not None
    assert shadow.artifacts.backup.backup_branch == "agent-backup/sync"


def test_sync_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(settings, "TMS_ADAPTER_ENABLED", False)
    sync_tms_from_legacy(task_id="t1", react_step=1)
    shadow = get_shadow()
    assert shadow.workflow.state == MutationWorkflowState.ANALYZING
