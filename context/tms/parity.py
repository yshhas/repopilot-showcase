"""TMS parity comparison (PR-M1)."""

from __future__ import annotations

from context.tms.types import BackupRef, TaskMutationState


def _normalize_paths(paths: list[str]) -> list[str]:
    return sorted(str(item).strip().replace("\\", "/") for item in paths if str(item).strip())


def _backup_equal(left: BackupRef | None, right: BackupRef | None) -> bool:
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    return (
        left.backup_branch == right.backup_branch
        and left.backup_commit == right.backup_commit
        and left.original_branch == right.original_branch
    )


def check_tms_parity(
    canonical: TaskMutationState,
    shadow: TaskMutationState,
) -> list[str]:
    """Return list of mismatch field paths; empty if equivalent."""
    mismatches: list[str] = []

    if canonical.workflow.state != shadow.workflow.state:
        mismatches.append("workflow.state")
    if canonical.workflow.path != shadow.workflow.path:
        mismatches.append("workflow.path")
    if canonical.workflow.proposal_digest != shadow.workflow.proposal_digest:
        mismatches.append("workflow.proposal_digest")

    if not _backup_equal(canonical.artifacts.backup, shadow.artifacts.backup):
        mismatches.append("artifacts.backup")

    if _normalize_paths(canonical.artifacts.diff_previewed_paths) != _normalize_paths(
        shadow.artifacts.diff_previewed_paths
    ):
        mismatches.append("artifacts.diff_previewed_paths")

    if canonical.artifacts.patch_applied != shadow.artifacts.patch_applied:
        mismatches.append("artifacts.patch_applied")

    if _normalize_paths(canonical.artifacts.patch_applied_paths) != _normalize_paths(
        shadow.artifacts.patch_applied_paths
    ):
        mismatches.append("artifacts.patch_applied_paths")

    if canonical.epoch != shadow.epoch:
        mismatches.append("epoch")

    return mismatches
