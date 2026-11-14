"""Single advancement entry: ToolOutcome → TMS (PR-M2, PR-M5-b)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from audit.audit_log import write_audit_event
from context.tms.context import get_shadow
from context.tms.types import (
    BackupRef,
    MilestoneToken,
    MutationPath,
    MutationWorkflowState,
    TaskMutationState,
    parse_milestone_token,
)
from tools.result_schema import is_tool_reject


@dataclass(frozen=True)
class AdvanceResult:
    advanced: bool
    milestone: MilestoneToken | None
    legacy_mirrored: bool
    tms_updated: bool


def _normalize_paths(paths: list[str] | None) -> list[str]:
    if not paths:
        return []
    return [str(item).strip().replace("\\", "/") for item in paths if str(item).strip()]


def _paths_from(outcome_details: dict[str, Any], args: dict[str, Any] | None) -> list[str]:
    paths = outcome_details.get("paths")
    if isinstance(paths, list) and paths:
        return _normalize_paths(paths)
    return _extract_paths_from_args(args)


def _extract_paths_from_args(args: dict[str, Any] | None) -> list[str]:
    from schemas import normalize_to_changes

    payload = args or {}
    changes, error = normalize_to_changes(
        path=payload.get("path"),
        new_content=payload.get("new_content"),
        changes=payload.get("changes"),
    )
    if error or not changes:
        single = str(payload.get("path") or "").strip().replace("\\", "/")
        return [single] if single else []
    return [str(item.path).strip().replace("\\", "/") for item in changes]


def _clear_artifact_milestones(state: TaskMutationState) -> None:
    state.artifacts.backup = None
    state.artifacts.diff_previewed_paths = []
    state.artifacts.patch_applied = False
    state.artifacts.patch_applied_paths = []


def _apply_milestone_to_tms(
    token: MilestoneToken,
    *,
    tool: str,
    args: dict[str, Any] | None,
    details: dict[str, Any],
) -> None:
    state = get_shadow()
    workflow = state.workflow
    artifacts = state.artifacts

    if token == MilestoneToken.PROPOSED:
        digest = str(details.get("proposal_digest") or "").strip() or None
        if digest and workflow.proposal_digest and workflow.proposal_digest != digest:
            _clear_artifact_milestones(state)
        workflow.proposal_digest = digest
        workflow.state = MutationWorkflowState.PROPOSED
        return

    if token == MilestoneToken.DIFF_GENERATED:
        paths = _paths_from(details, args)
        if not paths:
            return
        workflow.state = MutationWorkflowState.DIFF_PREVIEWED
        workflow.path = MutationPath.DIFF_FIRST
        merged = list(artifacts.diff_previewed_paths)
        for path in paths:
            if path not in merged:
                merged.append(path)
        artifacts.diff_previewed_paths = merged
        return

    if token == MilestoneToken.BACKUP_CREATED:
        branch = str(details.get("backup_branch") or "").strip()
        commit = str(details.get("backup_commit") or "").strip()
        original = str(details.get("original_branch") or "main").strip() or "main"
        previous_state = workflow.state
        previous_path = workflow.path
        workflow.state = MutationWorkflowState.BACKED_UP
        if (
            previous_state == MutationWorkflowState.PROPOSED
            and previous_path == MutationPath.NONE
        ):
            workflow.path = MutationPath.WRITE_FALLBACK
        if branch and commit:
            step = details.get("created_at_step")
            created_at_step = int(step) if step is not None else None
            artifacts.backup = BackupRef(
                backup_branch=branch,
                backup_commit=commit,
                original_branch=original,
                created_at_step=created_at_step,
            )
        return

    if token == MilestoneToken.PATCH_APPLIED:
        paths = _paths_from(details, args)
        if not paths:
            return
        workflow.state = MutationWorkflowState.PATCHED
        artifacts.patch_applied = True
        artifacts.patch_applied_paths = paths
        return

    if token == MilestoneToken.FILE_WRITTEN:
        paths = _paths_from(details, args)
        if not paths:
            return
        workflow.state = MutationWorkflowState.PATCHED
        workflow.path = MutationPath.WRITE_FALLBACK
        artifacts.patch_applied = True
        artifacts.patch_applied_paths = paths
        return

    if token == MilestoneToken.ROLLBACK_TO_BACKUP:
        workflow.state = MutationWorkflowState.BACKED_UP
        artifacts.patch_applied = False
        artifacts.patch_applied_paths = []
        return


def advance_from_outcome(
    outcome: Any,
    *,
    tool: str,
    args: dict[str, Any] | None = None,
) -> AdvanceResult:
    from tools.outcome_schema import is_tool_success

    if isinstance(outcome, str) or is_tool_reject(outcome):
        return AdvanceResult(False, None, False, False)

    if not is_tool_success(outcome):
        return AdvanceResult(False, None, False, False)

    token = parse_milestone_token(outcome.get("milestone"))
    if token is None:
        return AdvanceResult(False, None, False, False)

    if token == MilestoneToken.DEDUP_SKIPPED:
        return AdvanceResult(False, None, False, False)

    details = dict(outcome.get("details") or {})

    try:
        _apply_milestone_to_tms(token, tool=tool, args=args, details=details)
        tms_updated = True
    except Exception as exc:
        write_audit_event(
            {
                "event": "tms_advance_failed",
                "tool": tool,
                "milestone": token.value,
                "error": str(exc),
            }
        )
        return AdvanceResult(False, token, False, False)

    write_audit_event(
        {
            "event": "outcome_advanced",
            "tool": tool,
            "milestone": token.value,
            "code": outcome.get("code"),
            "legacy_mirrored": False,
        }
    )

    return AdvanceResult(True, token, False, tms_updated)
