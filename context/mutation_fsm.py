"""Runtime mutation workflow FSM (v0.9 PR-F1)."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
from typing import Any

import config.settings as settings
from context.execution_state import compute_proposal_digest
from context.tms.types import MilestoneToken
from schemas import normalize_to_changes
from tools.result_schema import (
    FSM_REJECT_PREFIX,
    REJECT_CODE_MUTATION_FSM_BLOCKED,
    ToolRejectResult,
    ToolResult,
    is_tool_reject,
    tool_reject,
    tool_result_message,
)

PROPOSAL_MARKER = "修改方案"
BACKUP_SUCCESS_MARKER = "Git 备份完成"
PATCH_SUCCESS_MARKER = "Patch 应用完成"
WRITE_SUCCESS_MARKER = "文件写入完成"
ROLLBACK_SUCCESS_MARKER = "Git 回滚完成"

FSM_REJECT_CODE = REJECT_CODE_MUTATION_FSM_BLOCKED
MUTATION_FSM_SNAPSHOT_VERSION = 1

MUTATION_FSM_TOOLS = frozenset({
    "propose_code_changes",
    "generate_unified_diff",
    "git_create_backup",
    "apply_patch",
    "write_repo_file",
    "git_rollback",
})


class MutationWorkflowState(str, Enum):
    ANALYZING = "ANALYZING"
    PROPOSED = "PROPOSED"
    DIFF_PREVIEWED = "DIFF_PREVIEWED"
    BACKED_UP = "BACKED_UP"
    PATCHED = "PATCHED"
    DONE = "DONE"


class MutationPath(str, Enum):
    NONE = "NONE"
    DIFF_FIRST = "DIFF_FIRST"
    WRITE_FALLBACK = "WRITE_FALLBACK"


@dataclass
class MutationFsmContext:
    state: MutationWorkflowState = MutationWorkflowState.ANALYZING
    mutation_path: MutationPath = MutationPath.NONE
    proposal_digest: str | None = None


_mutation_fsm: ContextVar[MutationFsmContext | None] = ContextVar(
    "mutation_fsm",
    default=None,
)


def is_mutation_fsm_enabled() -> bool:
    return settings.MUTATION_FSM_ENABLED


def reset_mutation_fsm() -> None:
    _mutation_fsm.set(MutationFsmContext())


def mark_mutation_fsm_done() -> None:
    if not is_mutation_fsm_enabled():
        return

    ctx = get_mutation_fsm_context()
    ctx.state = MutationWorkflowState.DONE


def get_mutation_fsm_context() -> MutationFsmContext:
    ctx = _mutation_fsm.get()
    if ctx is None:
        ctx = MutationFsmContext()
        _mutation_fsm.set(ctx)
    return ctx


def export_mutation_fsm_snapshot() -> dict[str, Any]:
    if not is_mutation_fsm_enabled():
        return {}

    ctx = get_mutation_fsm_context()
    return {
        "version": MUTATION_FSM_SNAPSHOT_VERSION,
        "state": ctx.state.value,
        "mutation_path": ctx.mutation_path.value,
        "proposal_digest": ctx.proposal_digest,
    }


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _snapshot_state_path(raw: dict[str, Any]) -> tuple[MutationWorkflowState, MutationPath]:
    state = MutationWorkflowState(str(raw["state"]))
    path = MutationPath(str(raw["mutation_path"]))
    return state, path


def restore_mutation_fsm(raw: dict[str, Any] | None) -> None:
    if not is_mutation_fsm_enabled():
        reset_mutation_fsm()
        return

    if not raw:
        reset_mutation_fsm()
        return

    version = raw.get("version", MUTATION_FSM_SNAPSHOT_VERSION)
    if version != MUTATION_FSM_SNAPSHOT_VERSION:
        reset_mutation_fsm()
        return

    try:
        state, path = _snapshot_state_path(raw)
    except ValueError:
        reset_mutation_fsm()
        return

    _mutation_fsm.set(
        MutationFsmContext(
            state=state,
            mutation_path=path,
            proposal_digest=_optional_str(raw.get("proposal_digest")),
        )
    )


def derive_mutation_fsm_from_execution_state(
    execution_state: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Compatibility fallback when checkpoint has no mutation_fsm_json."""
    if not execution_state:
        return None

    preview_paths = execution_state.get("diff_previewed_paths")
    if not isinstance(preview_paths, list):
        preview_paths = []

    has_preview = bool(preview_paths)
    proposal_digest = _optional_str(execution_state.get("proposal_digest"))

    if execution_state.get("patch_applied"):
        state = MutationWorkflowState.PATCHED
        path = (
            MutationPath.DIFF_FIRST
            if has_preview
            else MutationPath.WRITE_FALLBACK
        )
    elif _optional_str(execution_state.get("backup_branch")):
        state = MutationWorkflowState.BACKED_UP
        path = (
            MutationPath.DIFF_FIRST
            if has_preview
            else MutationPath.WRITE_FALLBACK
        )
    elif has_preview:
        state = MutationWorkflowState.DIFF_PREVIEWED
        path = MutationPath.DIFF_FIRST
    elif proposal_digest:
        state = MutationWorkflowState.PROPOSED
        path = MutationPath.NONE
    else:
        return None

    return {
        "version": MUTATION_FSM_SNAPSHOT_VERSION,
        "state": state.value,
        "mutation_path": path.value,
        "proposal_digest": proposal_digest,
    }


def snapshots_compatible(
    snapshot: dict[str, Any],
    derived: dict[str, Any],
) -> bool:
    try:
        snap_state, snap_path = _snapshot_state_path(snapshot)
        derived_state, derived_path = _snapshot_state_path(derived)
    except ValueError:
        return False

    return snap_state == derived_state and snap_path == derived_path


def hydrate_mutation_fsm_from_checkpoint(
    snapshot: dict[str, Any] | None,
    execution_state: dict[str, Any] | None,
) -> tuple[str, bool]:
    """Restore FSM on resume. Returns (source, derive_mismatch)."""
    if not is_mutation_fsm_enabled():
        reset_mutation_fsm()
        return "disabled", False

    if snapshot:
        restore_mutation_fsm(snapshot)
        mismatch = False
        derived = derive_mutation_fsm_from_execution_state(execution_state)
        if derived and not snapshots_compatible(snapshot, derived):
            mismatch = True
        return "snapshot", mismatch

    derived = derive_mutation_fsm_from_execution_state(execution_state)
    if derived:
        restore_mutation_fsm(derived)
        return "derived", False

    reset_mutation_fsm()
    return "reset", False


def build_mutation_fsm_blocked_audit(
    tool: str,
    reject: ToolRejectResult | str,
) -> dict[str, Any]:
    ctx = get_mutation_fsm_context()
    required_state = "unknown"
    mutation_path = ctx.mutation_path.value

    if is_tool_reject(reject):
        details = reject.get("details") or {}
        required_state = str(details.get("required_state") or "unknown")
        mutation_path = str(details.get("mutation_path") or mutation_path)
    else:
        reject_message = str(reject or "")
        marker = "required="
        if marker in reject_message:
            required_state = reject_message.split(marker, 1)[1].split()[0]

    return {
        "event": "mutation_fsm_blocked",
        "tool": tool,
        "current_state": ctx.state.value,
        "required_state": required_state,
        "mutation_path": mutation_path,
        "reason": "illegal_transition",
        "code": FSM_REJECT_CODE,
    }


def _build_fsm_reject(
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
    if path is not None:
        parts.append(f"path={path.value}")
    parts.append(f"code={FSM_REJECT_CODE}")

    details: dict[str, Any] = {
        "tool": tool,
        "current_state": current.value,
        "required_state": required,
        "reason": "illegal_transition",
    }
    if path is not None:
        details["mutation_path"] = path.value
    else:
        details["mutation_path"] = get_mutation_fsm_context().mutation_path.value

    return tool_reject(
        FSM_REJECT_CODE,
        " ".join(parts),
        details=details,
    )


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
        single_path = _normalize_path(str(payload.get("path") or ""))
        return [single_path] if single_path else []

    return [_normalize_path(item.path) for item in changes]


def _is_success_marker(result: str, marker: str) -> bool:
    return marker in str(result or "")


def is_fsm_reject_result(result: ToolResult) -> bool:
    if is_tool_reject(result):
        return result.get("code") == FSM_REJECT_CODE
    return str(result or "").startswith(FSM_REJECT_PREFIX)


def check_mutation_fsm_allowed(
    tool: str,
    args: dict[str, Any] | None,
    *,
    agent_mode: str,
) -> ToolRejectResult | None:
    if not is_mutation_fsm_enabled():
        return None

    if tool not in MUTATION_FSM_TOOLS:
        return None

    ctx = get_mutation_fsm_context()
    state = ctx.state
    path = ctx.mutation_path

    if state == MutationWorkflowState.DONE:
        return _build_fsm_reject(tool, state, "non-terminal workflow state")

    if tool == "propose_code_changes":
        if state in {
            MutationWorkflowState.ANALYZING,
            MutationWorkflowState.PROPOSED,
            MutationWorkflowState.PATCHED,
        }:
            return None
        return _build_fsm_reject(
            tool,
            state,
            "ANALYZING|PROPOSED|PATCHED",
            path=path,
        )

    if tool == "generate_unified_diff":
        if path == MutationPath.WRITE_FALLBACK:
            return _build_fsm_reject(
                tool,
                state,
                "mutation_path!=WRITE_FALLBACK",
                path=path,
            )
        if state in {MutationWorkflowState.PROPOSED, MutationWorkflowState.DIFF_PREVIEWED}:
            return None
        return _build_fsm_reject(tool, state, "PROPOSED", path=path)

    if tool == "git_create_backup":
        if path == MutationPath.DIFF_FIRST:
            if state in {
                MutationWorkflowState.DIFF_PREVIEWED,
                MutationWorkflowState.BACKED_UP,
            }:
                return None
            return _build_fsm_reject(
                tool,
                state,
                "DIFF_PREVIEWED|BACKED_UP",
                path=path,
            )

        if path == MutationPath.WRITE_FALLBACK:
            if state == MutationWorkflowState.BACKED_UP:
                return None
            return _build_fsm_reject(
                tool,
                state,
                "BACKED_UP (write-fallback re-backup)",
                path=path,
            )

        if state == MutationWorkflowState.PROPOSED:
            return None

        return _build_fsm_reject(
            tool,
            state,
            "PROPOSED (write-fallback) or DIFF_PREVIEWED (diff-first)",
            path=path,
        )

    if tool == "apply_patch":
        if path != MutationPath.DIFF_FIRST:
            return _build_fsm_reject(
                tool,
                state,
                "BACKED_UP with path=DIFF_FIRST",
                path=path,
            )
        if state != MutationWorkflowState.BACKED_UP:
            return _build_fsm_reject(
                tool,
                state,
                "BACKED_UP",
                path=path,
            )
        return None

    if tool == "write_repo_file":
        if path == MutationPath.DIFF_FIRST:
            return _build_fsm_reject(
                tool,
                state,
                "mutation_path!=DIFF_FIRST",
                path=path,
            )
        if state != MutationWorkflowState.BACKED_UP:
            return _build_fsm_reject(
                tool,
                state,
                "BACKED_UP with path=WRITE_FALLBACK",
                path=path,
            )
        if path != MutationPath.WRITE_FALLBACK:
            return _build_fsm_reject(
                tool,
                state,
                "BACKED_UP with path=WRITE_FALLBACK",
                path=path,
            )
        return None

    if tool == "git_rollback":
        if state in {MutationWorkflowState.BACKED_UP, MutationWorkflowState.PATCHED}:
            return None
        return _build_fsm_reject(tool, state, "BACKED_UP|PATCHED", path=path)

    return None


def _clear_downstream_milestones(ctx: MutationFsmContext) -> None:
    ctx.mutation_path = MutationPath.NONE


def advance_mutation_fsm_on_success(
    tool: str,
    args: dict[str, Any] | None,
    result: ToolResult,
) -> None:
    if not is_mutation_fsm_enabled():
        return

    if tool not in MUTATION_FSM_TOOLS:
        return

    if is_fsm_reject_result(result):
        return

    text = tool_result_message(result)

    if text.startswith("用户已取消执行工具"):
        return

    if text.startswith("跳过重复"):
        return

    if text.startswith("参数错误"):
        return

    ctx = get_mutation_fsm_context()

    if tool == "propose_code_changes":
        if PROPOSAL_MARKER not in text:
            return

        digest = compute_proposal_digest(text)
        if not digest:
            return

        if ctx.proposal_digest and ctx.proposal_digest != digest:
            _clear_downstream_milestones(ctx)

        ctx.proposal_digest = digest
        ctx.state = MutationWorkflowState.PROPOSED
        return

    if tool == "generate_unified_diff":
        if "diff" not in text.lower() and "Diff" not in text:
            return

        if not _extract_patch_paths(args):
            return

        ctx.state = MutationWorkflowState.DIFF_PREVIEWED
        ctx.mutation_path = MutationPath.DIFF_FIRST
        return

    if tool == "git_create_backup":
        if not _is_success_marker(text, BACKUP_SUCCESS_MARKER):
            return

        previous_state = ctx.state
        previous_path = ctx.mutation_path
        ctx.state = MutationWorkflowState.BACKED_UP

        if (
            previous_state == MutationWorkflowState.PROPOSED
            and previous_path == MutationPath.NONE
        ):
            ctx.mutation_path = MutationPath.WRITE_FALLBACK
        return

    if tool == "apply_patch":
        if not _is_success_marker(text, PATCH_SUCCESS_MARKER):
            return

        ctx.state = MutationWorkflowState.PATCHED
        return

    if tool == "write_repo_file":
        if not _is_success_marker(text, WRITE_SUCCESS_MARKER):
            return

        ctx.state = MutationWorkflowState.PATCHED
        ctx.mutation_path = MutationPath.WRITE_FALLBACK
        return

    if tool == "git_rollback":
        if not _is_success_marker(text, ROLLBACK_SUCCESS_MARKER):
            return

        ctx.state = MutationWorkflowState.BACKED_UP
        return


def apply_milestone_token(
    token: MilestoneToken,
    *,
    tool: str,
    args: dict[str, Any] | None,
    details: dict[str, Any] | None,
) -> None:
    """Structured milestone mirror (PR-M2) — called only from advance_from_outcome."""
    from context.tms.types import MilestoneToken as MsToken

    if not is_mutation_fsm_enabled():
        return

    if tool not in MUTATION_FSM_TOOLS:
        return

    payload = dict(details or {})
    ctx = get_mutation_fsm_context()

    if token == MsToken.PROPOSED:
        digest = str(payload.get("proposal_digest") or "").strip() or None
        if not digest:
            return
        if ctx.proposal_digest and ctx.proposal_digest != digest:
            _clear_downstream_milestones(ctx)
        ctx.proposal_digest = digest
        ctx.state = MutationWorkflowState.PROPOSED
        return

    if token == MsToken.DIFF_GENERATED:
        if not _extract_patch_paths(args):
            return
        ctx.state = MutationWorkflowState.DIFF_PREVIEWED
        ctx.mutation_path = MutationPath.DIFF_FIRST
        return

    if token == MsToken.BACKUP_CREATED:
        previous_state = ctx.state
        previous_path = ctx.mutation_path
        ctx.state = MutationWorkflowState.BACKED_UP
        if (
            previous_state == MutationWorkflowState.PROPOSED
            and previous_path == MutationPath.NONE
        ):
            ctx.mutation_path = MutationPath.WRITE_FALLBACK
        return

    if token == MsToken.PATCH_APPLIED:
        ctx.state = MutationWorkflowState.PATCHED
        return

    if token == MsToken.FILE_WRITTEN:
        ctx.state = MutationWorkflowState.PATCHED
        ctx.mutation_path = MutationPath.WRITE_FALLBACK
        return

    if token == MsToken.ROLLBACK_TO_BACKUP:
        ctx.state = MutationWorkflowState.BACKED_UP
        return
