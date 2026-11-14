"""Task-scoped backup resolution (PR-M4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import config.settings as settings
from audit.audit_log import write_audit_event
from audit.context import get_task_id
from context.tms.context import get_shadow
from context.tms.types import BackupRef


BackupSource = Literal["tms", "legacy_execution", "global_file"]


@dataclass(frozen=True)
class ResolvedBackupRef:
    backup_branch: str
    backup_commit: str
    original_branch: str
    source: BackupSource
    task_id: str | None = None


def _optional_str(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _ref_from_backup(backup: BackupRef, *, source: BackupSource, task_id: str | None) -> ResolvedBackupRef:
    return ResolvedBackupRef(
        backup_branch=backup.backup_branch,
        backup_commit=backup.backup_commit,
        original_branch=backup.original_branch or "main",
        source=source,
        task_id=task_id,
    )


def _resolve_from_tms() -> BackupRef | None:
    backup = get_shadow().artifacts.backup
    if backup is None:
        return None
    if not backup.backup_branch or not backup.backup_commit:
        return None
    return backup


def _resolve_from_legacy_execution() -> BackupRef | None:
    from context.execution_state import get_execution_state

    state = get_execution_state()
    branch = _optional_str(state.backup_branch)
    commit = _optional_str(state.backup_commit)
    if not branch or not commit:
        return None

    from context.project_context import get_original_branch

    return BackupRef(
        backup_branch=branch,
        backup_commit=commit,
        original_branch=get_original_branch() or "main",
    )


def _resolve_from_global_file() -> BackupRef | None:
    from context.project_context import (
        get_backup_branch,
        get_backup_commit,
        get_original_branch,
    )

    branch = _optional_str(get_backup_branch())
    commit = _optional_str(get_backup_commit())
    if not branch or not commit:
        return None

    return BackupRef(
        backup_branch=branch,
        backup_commit=commit,
        original_branch=get_original_branch() or "main",
    )


def _audit_backup_ref_resolved(ref: ResolvedBackupRef) -> None:
    write_audit_event(
        {
            "event": "backup_ref_resolved",
            "task_id": ref.task_id,
            "backup_source": ref.source,
            "backup_branch": ref.backup_branch,
            "backup_commit": ref.backup_commit,
            "original_branch": ref.original_branch,
        }
    )


def _audit_backup_gate_mismatch(
    *,
    task_id: str | None,
    tms_ref: BackupRef,
    global_ref: BackupRef,
) -> None:
    write_audit_event(
        {
            "event": "backup_gate_mismatch",
            "task_id": task_id,
            "tms_branch": tms_ref.backup_branch,
            "tms_commit": tms_ref.backup_commit,
            "global_branch": global_ref.backup_branch,
            "global_commit": global_ref.backup_commit,
        }
    )


def _check_tms_global_divergence(*, task_id: str | None) -> None:
    if not settings.TASK_SCOPED_BACKUP_ENABLED:
        return

    tms_ref = _resolve_from_tms()
    global_ref = _resolve_from_global_file()
    if tms_ref is None or global_ref is None:
        return
    if (
        tms_ref.backup_branch == global_ref.backup_branch
        and tms_ref.backup_commit == global_ref.backup_commit
    ):
        return
    _audit_backup_gate_mismatch(
        task_id=task_id,
        tms_ref=tms_ref,
        global_ref=global_ref,
    )


def resolve_task_backup_ref(
    *,
    task_id: str | None = None,
    audit: bool = True,
) -> ResolvedBackupRef | None:
    """Unified backup read entry — TMS-first when task-scoped backup is enabled."""
    effective_task_id = task_id if task_id is not None else get_task_id()

    if settings.TASK_SCOPED_BACKUP_ENABLED:
        _check_tms_global_divergence(task_id=effective_task_id)

        tms_ref = _resolve_from_tms()
        if tms_ref is not None:
            resolved = _ref_from_backup(
                tms_ref,
                source="tms",
                task_id=effective_task_id,
            )
            if audit:
                _audit_backup_ref_resolved(resolved)
            return resolved

        legacy_ref = _resolve_from_legacy_execution()
        if legacy_ref is not None:
            resolved = _ref_from_backup(
                legacy_ref,
                source="legacy_execution",
                task_id=effective_task_id,
            )
            if audit:
                _audit_backup_ref_resolved(resolved)
            return resolved

        global_ref = _resolve_from_global_file()
        if global_ref is not None:
            resolved = _ref_from_backup(
                global_ref,
                source="global_file",
                task_id=effective_task_id,
            )
            if audit:
                _audit_backup_ref_resolved(resolved)
            return resolved

        return None

    global_ref = _resolve_from_global_file()
    if global_ref is not None:
        resolved = _ref_from_backup(
            global_ref,
            source="global_file",
            task_id=effective_task_id,
        )
        if audit:
            _audit_backup_ref_resolved(resolved)
        return resolved

    legacy_ref = _resolve_from_legacy_execution()
    if legacy_ref is not None:
        resolved = _ref_from_backup(
            legacy_ref,
            source="legacy_execution",
            task_id=effective_task_id,
        )
        if audit:
            _audit_backup_ref_resolved(resolved)
        return resolved

    return None


def has_task_backup_record(
    *,
    task_id: str | None = None,
    audit: bool = True,
) -> bool:
    return resolve_task_backup_ref(task_id=task_id, audit=audit) is not None


def backup_create_persistence_note() -> str:
    """User-facing note after git_create_backup (PR-M4).

    When task-scoped backup is on and global dual-write is off, do not imply
    that logs/last_backup.json was updated.
    """
    if not settings.TASK_SCOPED_BACKUP_ENABLED:
        return (
            "说明: 已切回原分支，可继续后续修改流程；"
            "备份信息已写入 logs/last_backup.json。"
        )
    if settings.BACKUP_GLOBAL_DUAL_WRITE:
        return (
            "说明: 已切回原分支，可继续后续修改流程；"
            "备份信息已写入当前 task（checkpoint / TMS）"
            "与 logs/last_backup.json（dual-write）。"
        )
    return (
        "说明: 已切回原分支，可继续后续修改流程；"
        "备份信息已关联当前 task（checkpoint / TMS），未写入 global last_backup.json。"
    )


def maybe_persist_global_backup_dual_write(
    *,
    backup_branch: str,
    backup_commit: str,
    original_branch: str,
) -> None:
    """Persist backup to global file when migration flags allow."""
    from context.project_context import set_backup_info

    if not settings.TASK_SCOPED_BACKUP_ENABLED:
        set_backup_info(backup_branch, backup_commit, original_branch)
        return

    if settings.BACKUP_GLOBAL_DUAL_WRITE:
        set_backup_info(backup_branch, backup_commit, original_branch)
        write_audit_event(
            {
                "event": "backup_global_dual_write",
                "task_id": get_task_id(),
                "backup_branch": backup_branch,
                "backup_commit": backup_commit,
                "original_branch": original_branch,
            }
        )
