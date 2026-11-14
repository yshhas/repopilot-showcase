"""Legacy ↔ TMS adapter — sole module that reads legacy mutation state (PR-M1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import config.settings as settings
from audit.audit_log import write_audit_event
from context.tms.context import get_shadow, set_shadow
from context.tms.parity import check_tms_parity
from context.tms.types import (
    TMS_SCHEMA_VERSION,
    ArtifactSlice,
    BackupRef,
    MutationPath,
    MutationWorkflowState,
    TaskMutationState,
    VerificationSlice,
    VerificationStatus,
    WorkflowSlice,
    empty_mutation_state,
)


class ParityMismatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class ParityResult:
    ok: bool
    mismatches: list[str]
    resolution: str | None = None


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_path(path: str) -> str:
    return str(path or "").strip().replace("\\", "/")


def _legacy_execution_snapshot() -> dict[str, Any]:
    from context.execution_state import get_execution_state

    state = get_execution_state()
    return {
        "proposal_digest": state.proposal_digest,
        "backup_branch": state.backup_branch,
        "backup_commit": state.backup_commit,
        "diff_previewed_paths": list(state.diff_previewed_paths),
        "patch_applied": state.patch_applied,
        "patch_applied_paths": list(state.patch_applied_paths),
    }


def _legacy_workflow_snapshot(exec_snapshot: dict[str, Any]) -> dict[str, Any]:
    from context.mutation_fsm import (
        derive_mutation_fsm_from_execution_state,
        export_mutation_fsm_snapshot,
        is_mutation_fsm_enabled,
    )

    if is_mutation_fsm_enabled():
        exported = export_mutation_fsm_snapshot()
        if exported:
            return exported

    derived = derive_mutation_fsm_from_execution_state(exec_snapshot)
    if derived:
        return derived

    return {
        "state": MutationWorkflowState.ANALYZING.value,
        "mutation_path": MutationPath.NONE.value,
        "proposal_digest": exec_snapshot.get("proposal_digest"),
    }


def _backup_from_legacy(exec_snapshot: dict[str, Any]) -> BackupRef | None:
    branch = _optional_str(exec_snapshot.get("backup_branch"))
    commit = _optional_str(exec_snapshot.get("backup_commit"))
    original = "main"

    if branch and commit:
        from context.project_context import get_original_branch

        original_branch = get_original_branch() or original
        return BackupRef(
            backup_branch=branch,
            backup_commit=commit,
            original_branch=original_branch,
        )

    from context.project_context import (
        get_backup_branch,
        get_backup_commit,
        get_original_branch,
    )

    branch = get_backup_branch()
    commit = get_backup_commit()
    if not branch or not commit:
        return None

    return BackupRef(
        backup_branch=branch,
        backup_commit=commit,
        original_branch=get_original_branch() or original,
    )


def build_tms_from_legacy() -> TaskMutationState:
    """Read-only: legacy modules → canonical TaskMutationState."""
    exec_snapshot = _legacy_execution_snapshot()
    workflow_raw = _legacy_workflow_snapshot(exec_snapshot)

    try:
        workflow = WorkflowSlice(
            state=MutationWorkflowState(str(workflow_raw.get("state", "ANALYZING"))),
            path=MutationPath(str(workflow_raw.get("mutation_path", "NONE"))),
            proposal_digest=_optional_str(
                workflow_raw.get("proposal_digest") or exec_snapshot.get("proposal_digest")
            ),
        )
    except ValueError:
        workflow = WorkflowSlice()

    preview_paths = exec_snapshot.get("diff_previewed_paths")
    if not isinstance(preview_paths, list):
        preview_paths = []

    applied_paths = exec_snapshot.get("patch_applied_paths")
    if not isinstance(applied_paths, list):
        applied_paths = []

    artifacts = ArtifactSlice(
        backup=_backup_from_legacy(exec_snapshot),
        diff_previewed_paths=[
            _normalize_path(item) for item in preview_paths if _normalize_path(item)
        ],
        patch_applied=bool(exec_snapshot.get("patch_applied")),
        patch_applied_paths=[
            _normalize_path(item) for item in applied_paths if _normalize_path(item)
        ],
    )

    return TaskMutationState(
        workflow=workflow,
        artifacts=artifacts,
        epoch=0,
        schema_version=TMS_SCHEMA_VERSION,
    )


def _workflow_to_dict(workflow: WorkflowSlice) -> dict[str, Any]:
    return {
        "state": workflow.state.value,
        "path": workflow.path.value,
        "proposal_digest": workflow.proposal_digest,
    }


def _backup_to_dict(backup: BackupRef | None) -> dict[str, Any] | None:
    if backup is None:
        return None
    return {
        "backup_branch": backup.backup_branch,
        "backup_commit": backup.backup_commit,
        "original_branch": backup.original_branch,
        "created_at_step": backup.created_at_step,
    }


def _artifacts_to_dict(artifacts: ArtifactSlice) -> dict[str, Any]:
    return {
        "backup": _backup_to_dict(artifacts.backup),
        "diff_previewed_paths": list(artifacts.diff_previewed_paths),
        "patch_applied": artifacts.patch_applied,
        "patch_applied_paths": list(artifacts.patch_applied_paths),
    }


def _verification_to_dict(verification: VerificationSlice | None) -> dict[str, Any]:
    current = verification if verification is not None else VerificationSlice()
    status = current.status
    if not isinstance(status, VerificationStatus):
        status = VerificationStatus.NONE
    return {
        "status": status.value,
        "last_code": current.last_code,
        "checks_run": list(current.checks_run),
        "failed_checks": list(current.failed_checks),
        "paths": list(current.paths),
        "message": current.message,
    }


def export_mutation_state_for_checkpoint(
    state: TaskMutationState | None = None,
) -> dict[str, Any]:
    """Persistence export for mutation_state_json — no runtime meta."""
    current = state if state is not None else get_shadow()
    return {
        "schema_version": TMS_SCHEMA_VERSION,
        "workflow": _workflow_to_dict(current.workflow),
        "artifacts": _artifacts_to_dict(current.artifacts),
        "verification": _verification_to_dict(current.verification),
        "epoch": current.epoch,
    }


def export_mutation_state_v1(
    state: TaskMutationState | None = None,
    *,
    task_id: str | None = None,
    react_step: int | None = None,
) -> dict[str, Any]:
    current = state if state is not None else get_shadow()
    return {
        "schema_version": TMS_SCHEMA_VERSION,
        "workflow": _workflow_to_dict(current.workflow),
        "artifacts": _artifacts_to_dict(current.artifacts),
        "verification": _verification_to_dict(current.verification),
        "epoch": current.epoch,
        "meta": {
            "synced_from": "legacy",
            "synced_at_step": react_step,
            "task_id": task_id,
        },
    }


def _backup_from_dict(raw: dict[str, Any] | None) -> BackupRef | None:
    if not raw or not isinstance(raw, dict):
        return None

    branch = _optional_str(raw.get("backup_branch"))
    commit = _optional_str(raw.get("backup_commit"))
    original = _optional_str(raw.get("original_branch")) or "main"
    if not branch or not commit:
        return None

    step = raw.get("created_at_step")
    created_at_step = int(step) if step is not None else None

    return BackupRef(
        backup_branch=branch,
        backup_commit=commit,
        original_branch=original,
        created_at_step=created_at_step,
    )


class CheckpointHydrateError(RuntimeError):
    """Corrupted or unsupported mutation_state_json — resume should enter safe state."""


def hydrate_mutation_state_v1(
    raw: dict[str, Any] | None,
    *,
    strict: bool = False,
) -> TaskMutationState:
    """Import v1 blob; ignore unknown fields; unsupported version → empty TMS or raise."""
    if not raw or not isinstance(raw, dict):
        if strict:
            raise CheckpointHydrateError("mutation_state blob missing or not a dict")
        return empty_mutation_state()

    version = raw.get("schema_version", TMS_SCHEMA_VERSION)
    if not isinstance(version, int):
        try:
            version = int(version)
        except (TypeError, ValueError) as exc:
            if strict:
                raise CheckpointHydrateError("invalid schema_version") from exc
            version = TMS_SCHEMA_VERSION

    if version > TMS_SCHEMA_VERSION:
        write_audit_event(
            {
                "event": "tms_schema_unsupported",
                "schema_version": version,
                "supported_max": TMS_SCHEMA_VERSION,
            }
        )
        if strict:
            raise CheckpointHydrateError(
                "unsupported mutation_state schema_version: " + str(version)
            )
        return empty_mutation_state()

    workflow_raw = raw.get("workflow") if isinstance(raw.get("workflow"), dict) else {}
    artifacts_raw = raw.get("artifacts") if isinstance(raw.get("artifacts"), dict) else {}

    try:
        workflow = WorkflowSlice(
            state=MutationWorkflowState(
                str(workflow_raw.get("state", MutationWorkflowState.ANALYZING.value))
            ),
            path=MutationPath(str(workflow_raw.get("path", MutationPath.NONE.value))),
            proposal_digest=_optional_str(workflow_raw.get("proposal_digest")),
        )
    except ValueError as exc:
        if strict:
            raise CheckpointHydrateError("invalid workflow fields in mutation_state") from exc
        workflow = WorkflowSlice()

    preview_paths = artifacts_raw.get("diff_previewed_paths")
    if not isinstance(preview_paths, list):
        preview_paths = []

    applied_paths = artifacts_raw.get("patch_applied_paths")
    if not isinstance(applied_paths, list):
        applied_paths = []

    artifacts = ArtifactSlice(
        backup=_backup_from_dict(artifacts_raw.get("backup")),
        diff_previewed_paths=[
            _normalize_path(item) for item in preview_paths if _normalize_path(item)
        ],
        patch_applied=bool(artifacts_raw.get("patch_applied")),
        patch_applied_paths=[
            _normalize_path(item) for item in applied_paths if _normalize_path(item)
        ],
    )

    verification_raw = (
        raw.get("verification") if isinstance(raw.get("verification"), dict) else {}
    )
    try:
        status = VerificationStatus(
            str(verification_raw.get("status", VerificationStatus.NONE.value))
        )
    except ValueError:
        status = VerificationStatus.NONE

    checks_run = verification_raw.get("checks_run")
    if not isinstance(checks_run, list):
        checks_run = []
    failed_checks = verification_raw.get("failed_checks")
    if not isinstance(failed_checks, list):
        failed_checks = []
    verify_paths = verification_raw.get("paths")
    if not isinstance(verify_paths, list):
        verify_paths = []

    verification = VerificationSlice(
        status=status,
        last_code=_optional_str(verification_raw.get("last_code")),
        checks_run=[str(item) for item in checks_run if str(item).strip()],
        failed_checks=[str(item) for item in failed_checks if str(item).strip()],
        paths=[
            _normalize_path(item) for item in verify_paths if _normalize_path(item)
        ],
        message=_optional_str(verification_raw.get("message")),
    )

    epoch_raw = raw.get("epoch", 0)
    try:
        epoch = int(epoch_raw)
    except (TypeError, ValueError):
        epoch = 0

    return TaskMutationState(
        workflow=workflow,
        artifacts=artifacts,
        verification=verification,
        epoch=epoch,
        schema_version=TMS_SCHEMA_VERSION,
    )


def _artifacts_from_execution_json(
    execution_state_json: dict[str, Any] | None,
) -> ArtifactSlice:
    if not execution_state_json or not isinstance(execution_state_json, dict):
        return ArtifactSlice()

    preview_paths = execution_state_json.get("diff_previewed_paths")
    if not isinstance(preview_paths, list):
        preview_paths = []

    applied_paths = execution_state_json.get("patch_applied_paths")
    if not isinstance(applied_paths, list):
        applied_paths = []

    branch = _optional_str(execution_state_json.get("backup_branch"))
    commit = _optional_str(execution_state_json.get("backup_commit"))
    backup = None
    if branch and commit:
        backup = BackupRef(
            backup_branch=branch,
            backup_commit=commit,
            original_branch="main",
        )
    else:
        backup = _backup_from_legacy(execution_state_json)

    return ArtifactSlice(
        backup=backup,
        diff_previewed_paths=[
            _normalize_path(item) for item in preview_paths if _normalize_path(item)
        ],
        patch_applied=bool(execution_state_json.get("patch_applied")),
        patch_applied_paths=[
            _normalize_path(item) for item in applied_paths if _normalize_path(item)
        ],
    )


def hydrate_mutation_state_from_v1_columns(
    *,
    mutation_fsm_json: dict[str, Any] | None,
    execution_state_json: dict[str, Any] | None,
) -> tuple[TaskMutationState, bool]:
    """Merge v0.9 execution_state + mutation_fsm columns into TMS."""
    from context.mutation_fsm import (
        MUTATION_FSM_SNAPSHOT_VERSION,
        derive_mutation_fsm_from_execution_state,
        snapshots_compatible,
    )

    artifacts = _artifacts_from_execution_json(execution_state_json)
    derive_mismatch = False

    exec_digest = None
    if execution_state_json and isinstance(execution_state_json, dict):
        exec_digest = _optional_str(execution_state_json.get("proposal_digest"))

    workflow = WorkflowSlice()
    fsm_json = mutation_fsm_json if isinstance(mutation_fsm_json, dict) else None
    derived = derive_mutation_fsm_from_execution_state(execution_state_json)

    if fsm_json and fsm_json.get("version") == MUTATION_FSM_SNAPSHOT_VERSION:
        try:
            workflow = WorkflowSlice(
                state=MutationWorkflowState(str(fsm_json["state"])),
                path=MutationPath(str(fsm_json["mutation_path"])),
                proposal_digest=_optional_str(fsm_json.get("proposal_digest"))
                or exec_digest,
            )
            if derived and not snapshots_compatible(fsm_json, derived):
                derive_mismatch = True
        except ValueError:
            workflow = WorkflowSlice()
            fsm_json = None

    if workflow.state == MutationWorkflowState.ANALYZING and derived:
        try:
            workflow = WorkflowSlice(
                state=MutationWorkflowState(str(derived["state"])),
                path=MutationPath(str(derived["mutation_path"])),
                proposal_digest=_optional_str(derived.get("proposal_digest"))
                or exec_digest,
            )
        except ValueError:
            pass
    elif workflow.proposal_digest is None and exec_digest:
        workflow.proposal_digest = exec_digest

    return (
        TaskMutationState(
            workflow=workflow,
            artifacts=artifacts,
            epoch=0,
            schema_version=TMS_SCHEMA_VERSION,
        ),
        derive_mismatch,
    )


def mirror_tms_to_legacy(state: TaskMutationState) -> None:
    """Resume compatibility: TMS shadow → legacy modules (adapter-only)."""
    from context.execution_state import restore_execution_state
    from context.mutation_fsm import (
        MUTATION_FSM_SNAPSHOT_VERSION,
        is_mutation_fsm_enabled,
        restore_mutation_fsm,
    )

    exec_payload: dict[str, Any] = {
        "proposal_digest": state.workflow.proposal_digest,
        "backup_branch": None,
        "backup_commit": None,
        "diff_previewed_paths": list(state.artifacts.diff_previewed_paths),
        "patch_applied": state.artifacts.patch_applied,
        "patch_applied_paths": list(state.artifacts.patch_applied_paths),
    }
    if state.artifacts.backup is not None:
        exec_payload["backup_branch"] = state.artifacts.backup.backup_branch
        exec_payload["backup_commit"] = state.artifacts.backup.backup_commit

    restore_execution_state(exec_payload)

    if state.artifacts.backup is not None:
        from context.tms.backup import maybe_persist_global_backup_dual_write

        maybe_persist_global_backup_dual_write(
            backup_branch=state.artifacts.backup.backup_branch,
            backup_commit=state.artifacts.backup.backup_commit,
            original_branch=state.artifacts.backup.original_branch,
        )

    if is_mutation_fsm_enabled():
        restore_mutation_fsm(
            {
                "version": MUTATION_FSM_SNAPSHOT_VERSION,
                "state": state.workflow.state.value,
                "mutation_path": state.workflow.path.value,
                "proposal_digest": state.workflow.proposal_digest,
            }
        )


def sync_tms_from_legacy(
    *,
    task_id: str | None = None,
    react_step: int | None = None,
) -> ParityResult:
    """
    One-way sync: legacy → TMS shadow only.
    Never writes back to legacy modules.
    """
    if not settings.TMS_ADAPTER_ENABLED:
        return ParityResult(ok=True, mismatches=[], resolution="adapter_disabled")

    canonical = build_tms_from_legacy()
    shadow_before = get_shadow()
    mismatches: list[str] = []

    if not _is_pristine_shadow(shadow_before):
        mismatches = check_tms_parity(canonical, shadow_before)

    resolution = None
    if mismatches:
        write_audit_event(
            {
                "event": "mutation_state_parity_mismatch",
                "task_id": task_id,
                "react_step": react_step,
                "mismatches": mismatches,
                "resolution": "legacy_wins",
            }
        )
        if settings.PARITY_STRICT:
            raise ParityMismatchError(
                "TMS parity mismatch: " + ", ".join(mismatches)
            )
        resolution = "legacy_wins"

    set_shadow(canonical)

    write_audit_event(
        {
            "event": "mutation_state_synced",
            "task_id": task_id,
            "react_step": react_step,
            "schema_version": TMS_SCHEMA_VERSION,
            "workflow_state": canonical.workflow.state.value,
            "parity_ok": not bool(mismatches),
        }
    )

    return ParityResult(
        ok=not bool(mismatches),
        mismatches=mismatches,
        resolution=resolution,
    )


def reset_mutation_state() -> None:
    """Clear TMS shadow only — does not mutate legacy."""
    from context.tms.context import clear_shadow

    clear_shadow()


def apply_checkpoint_hydrate_safe_state(
    *,
    task_id: str | None = None,
    react_step: int | None = None,
    error: str | None = None,
) -> None:
    """Corrupted v2 blob fallback — empty TMS + legacy reset."""
    from context.execution_state import reset_execution_state
    from context.mutation_fsm import reset_mutation_fsm

    write_audit_event(
        {
            "event": "checkpoint_hydrate_safe_state",
            "task_id": task_id,
            "react_step": react_step,
            "error": error,
        }
    )
    reset_mutation_state()
    reset_execution_state()
    reset_mutation_fsm()


def _is_pristine_shadow(shadow: TaskMutationState) -> bool:
    return (
        shadow.workflow.state == MutationWorkflowState.ANALYZING
        and shadow.workflow.path == MutationPath.NONE
        and shadow.workflow.proposal_digest is None
        and shadow.artifacts.backup is None
        and not shadow.artifacts.diff_previewed_paths
        and not shadow.artifacts.patch_applied
        and not shadow.artifacts.patch_applied_paths
        and shadow.epoch == 0
    )
