"""TMS-backed mutation guards and dedup (PR-M5-a).

When ``TMS_RUNTIME_SOT_ENABLED`` is on, ``tool_manager`` reads workflow and
artifact state from TMS shadow instead of legacy ``mutation_fsm`` /
``execution_state`` ContextVars.
"""

from __future__ import annotations

from typing import Any

import config.settings as settings
from context.tms.context import get_shadow
from context.tms.types import (
    MutationPath,
    MutationWorkflowState,
    TaskMutationState,
)
from schemas import normalize_to_changes
from tools.result_schema import (
    FSM_REJECT_PREFIX,
    REJECT_CODE_MUTATION_FSM_BLOCKED,
    ToolRejectResult,
    tool_reject,
)

MUTATION_GUARD_TOOLS = frozenset({
    "propose_code_changes",
    "generate_unified_diff",
    "git_create_backup",
    "apply_patch",
    "write_repo_file",
    "git_rollback",
    "verify_change",
})

DEDUP_GUARD_TOOLS = frozenset({
    "git_create_backup",
    "apply_patch",
    "write_repo_file",
})

FSM_REJECT_CODE = REJECT_CODE_MUTATION_FSM_BLOCKED


def is_tms_runtime_sot_enabled() -> bool:
    return settings.TMS_RUNTIME_SOT_ENABLED


def should_use_tms_runtime_guards() -> bool:
    """Return whether guard/dedup reads should use TMS shadow.

    PR-M5-f: ``tool_manager`` always routes through TMS readers; this helper
    remains for tests and migration audits.
    """
    if settings.TMS_RUNTIME_SOT_ENABLED:
        return True
    return settings.MUTATION_FSM_ENABLED or settings.EXECUTION_STATE_DEDUP_ENABLED


def is_mutation_guard_enabled() -> bool:
    return settings.MUTATION_FSM_ENABLED


def is_dedup_guard_enabled() -> bool:
    return settings.EXECUTION_STATE_DEDUP_ENABLED


def _workflow(state: TaskMutationState | None = None):
    return (state or get_shadow()).workflow


def _artifacts(state: TaskMutationState | None = None):
    return (state or get_shadow()).artifacts


def _normalize_path(path: str) -> str:
    return str(path or "").strip().replace("\\", "/")


def _extract_patch_paths(args: dict[str, Any] | None) -> list[str]:
    payload = args or {}
    changes, error = normalize_to_changes(
        path=payload.get("path"),
        new_content=payload.get("new_content"),
        changes=payload.get("changes"),
    )
    if error or not changes:
        single = _normalize_path(str(payload.get("path") or ""))
        return [single] if single else []
    return [_normalize_path(item.path) for item in changes]


def _build_guard_reject(
    tool: str,
    current: MutationWorkflowState,
    required: str,
    *,
    path: MutationPath | None = None,
) -> ToolRejectResult:
    parts = [
        FSM_REJECT_PREFIX,
        f"tool={tool}",
        f"current={current.value}",
        f"required={required}",
    ]
    workflow = _workflow()
    effective_path = path if path is not None else workflow.path
    if path is not None:
        parts.append(f"path={path.value}")
    parts.append(f"code={FSM_REJECT_CODE}")

    details: dict[str, Any] = {
        "tool": tool,
        "current_state": current.value,
        "required_state": required,
        "reason": "illegal_transition",
        "mutation_path": effective_path.value,
        "guard_source": "tms",
    }

    return tool_reject(
        FSM_REJECT_CODE,
        " ".join(parts),
        details=details,
    )


def build_mutation_guard_blocked_audit(
    tool: str,
    reject: ToolRejectResult | str,
) -> dict[str, Any]:
    workflow = _workflow()
    required_state = "unknown"
    mutation_path = workflow.path.value

    if isinstance(reject, dict):
        details = reject.get("details") or {}
        required_state = str(details.get("required_state") or "unknown")
        mutation_path = str(details.get("mutation_path") or mutation_path)

    return {
        "event": "mutation_fsm_blocked",
        "tool": tool,
        "current_state": workflow.state.value,
        "required_state": required_state,
        "mutation_path": mutation_path,
        "reason": "illegal_transition",
        "code": FSM_REJECT_CODE,
        "guard_source": "tms",
    }


def check_mutation_allowed(
    tool: str,
    args: dict[str, Any] | None,
    *,
    agent_mode: str,
) -> ToolRejectResult | None:
    """FSM guard reading TMS ``workflow`` slice."""
    del agent_mode  # reserved — mode gating handled upstream in tool_manager

    if not is_mutation_guard_enabled():
        return None

    if tool not in MUTATION_GUARD_TOOLS:
        return None

    workflow = _workflow()
    state = workflow.state
    path = workflow.path

    if state == MutationWorkflowState.DONE:
        return _build_guard_reject(tool, state, "non-terminal workflow state")

    if tool == "propose_code_changes":
        if state in {
            MutationWorkflowState.ANALYZING,
            MutationWorkflowState.PROPOSED,
            MutationWorkflowState.PATCHED,
        }:
            return None
        return _build_guard_reject(
            tool,
            state,
            "ANALYZING|PROPOSED|PATCHED",
            path=path,
        )

    if tool == "generate_unified_diff":
        if path == MutationPath.WRITE_FALLBACK:
            return _build_guard_reject(
                tool,
                state,
                "mutation_path!=WRITE_FALLBACK",
                path=path,
            )
        if state in {MutationWorkflowState.PROPOSED, MutationWorkflowState.DIFF_PREVIEWED}:
            return None
        return _build_guard_reject(tool, state, "PROPOSED", path=path)

    if tool == "git_create_backup":
        if path == MutationPath.DIFF_FIRST:
            if state in {
                MutationWorkflowState.DIFF_PREVIEWED,
                MutationWorkflowState.BACKED_UP,
            }:
                return None
            return _build_guard_reject(
                tool,
                state,
                "DIFF_PREVIEWED|BACKED_UP",
                path=path,
            )

        if path == MutationPath.WRITE_FALLBACK:
            if state == MutationWorkflowState.BACKED_UP:
                return None
            return _build_guard_reject(
                tool,
                state,
                "BACKED_UP (write-fallback re-backup)",
                path=path,
            )

        if state == MutationWorkflowState.PROPOSED:
            return None

        return _build_guard_reject(
            tool,
            state,
            "PROPOSED (write-fallback) or DIFF_PREVIEWED (diff-first)",
            path=path,
        )

    if tool == "apply_patch":
        if path != MutationPath.DIFF_FIRST:
            return _build_guard_reject(
                tool,
                state,
                "BACKED_UP with path=DIFF_FIRST",
                path=path,
            )
        if state != MutationWorkflowState.BACKED_UP:
            return _build_guard_reject(
                tool,
                state,
                "BACKED_UP",
                path=path,
            )
        return None

    if tool == "write_repo_file":
        if path == MutationPath.DIFF_FIRST:
            return _build_guard_reject(
                tool,
                state,
                "mutation_path!=DIFF_FIRST",
                path=path,
            )
        if state != MutationWorkflowState.BACKED_UP:
            return _build_guard_reject(
                tool,
                state,
                "BACKED_UP with path=WRITE_FALLBACK",
                path=path,
            )
        if path != MutationPath.WRITE_FALLBACK:
            return _build_guard_reject(
                tool,
                state,
                "BACKED_UP with path=WRITE_FALLBACK",
                path=path,
            )
        return None

    if tool == "git_rollback":
        if state in {MutationWorkflowState.BACKED_UP, MutationWorkflowState.PATCHED}:
            return None
        return _build_guard_reject(tool, state, "BACKED_UP|PATCHED", path=path)

    if tool == "verify_change":
        # Soft gate: verify only after a successful patch/write.
        if state == MutationWorkflowState.PATCHED:
            return None
        return _build_guard_reject(tool, state, "PATCHED", path=path)

    return None


def _backup_matches_resolved_ref(state: TaskMutationState) -> bool:
    backup = state.artifacts.backup
    if backup is None or not backup.backup_branch or not backup.backup_commit:
        return False

    from context.tms.backup import resolve_task_backup_ref

    resolved = resolve_task_backup_ref(audit=False)
    if resolved is None:
        return False

    return (
        backup.backup_branch == resolved.backup_branch
        and backup.backup_commit == resolved.backup_commit
    )


def should_skip_tool_tms(action: str, args: dict[str, Any] | None) -> str | None:
    """Dedup skip reading TMS ``artifacts`` slice."""
    if not is_dedup_guard_enabled():
        return None

    if action not in DEDUP_GUARD_TOOLS:
        return None

    state = get_shadow()
    artifacts = state.artifacts

    if action == "git_create_backup":
        backup = artifacts.backup
        if backup is None or not backup.backup_branch:
            return None
        if artifacts.patch_applied:
            return None

        if not _backup_matches_resolved_ref(state):
            return None

        return (
            "跳过重复 git_create_backup: 当前任务 checkpoint 已记录备份分支 "
            + backup.backup_branch
            + "，且 patch 尚未应用。如需重新备份请在追问中明确说明「重新备份」。"
        )

    if action in {"apply_patch", "write_repo_file"}:
        if not artifacts.patch_applied or not artifacts.patch_applied_paths:
            return None

        requested_paths = _extract_patch_paths(args)
        if action == "write_repo_file":
            single = _normalize_path(str((args or {}).get("path") or ""))
            requested_paths = [single] if single else requested_paths

        if sorted(requested_paths) != sorted(artifacts.patch_applied_paths):
            return None

        label = "apply_patch" if action == "apply_patch" else "write_repo_file"
        paths_text = ", ".join(artifacts.patch_applied_paths)
        return (
            "跳过重复 "
            + label
            + ": 当前任务 checkpoint 已记录对这些路径的成功写入 ("
            + paths_text
            + ")。如需再次修改请提交新的修改方案。"
        )

    return None
