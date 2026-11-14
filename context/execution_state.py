"""Per-task mutation milestone state for checkpoint resume dedup (v0.8 M1)."""

from __future__ import annotations

import hashlib
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import config.settings as settings
from context.project_context import get_backup_branch, get_backup_commit
from context.tms.types import MilestoneToken
from schemas import normalize_to_changes

BACKUP_SUCCESS_MARKER = "Git 备份完成"
PATCH_SUCCESS_MARKER = "Patch 应用完成"
WRITE_SUCCESS_MARKER = "文件写入完成"
PROPOSAL_MARKER = "修改方案"

RE_BACKUP_KEYWORDS = (
    "重新备份",
    "re-backup",
    "rebackup",
    "再次备份",
)


@dataclass
class ExecutionState:
    proposal_digest: str | None = None
    backup_branch: str | None = None
    backup_commit: str | None = None
    diff_previewed_paths: list[str] = field(default_factory=list)
    patch_applied: bool = False
    patch_applied_paths: list[str] = field(default_factory=list)


_execution_state: ContextVar[ExecutionState | None] = ContextVar(
    "execution_state",
    default=None,
)


def is_execution_state_dedup_enabled() -> bool:
    return settings.EXECUTION_STATE_DEDUP_ENABLED


def get_execution_state() -> ExecutionState:
    state = _execution_state.get()
    if state is None:
        state = ExecutionState()
        _execution_state.set(state)
    return state


def reset_execution_state() -> None:
    _execution_state.set(ExecutionState())


def export_execution_state() -> dict[str, Any]:
    if not is_execution_state_dedup_enabled():
        return {}

    state = get_execution_state()
    return {
        "proposal_digest": state.proposal_digest,
        "backup_branch": state.backup_branch,
        "backup_commit": state.backup_commit,
        "diff_previewed_paths": list(state.diff_previewed_paths),
        "patch_applied": state.patch_applied,
        "patch_applied_paths": list(state.patch_applied_paths),
    }


def restore_execution_state(raw: dict[str, Any] | None) -> None:
    if not raw:
        reset_execution_state()
        return

    paths = raw.get("diff_previewed_paths")
    if not isinstance(paths, list):
        paths = []

    applied_paths = raw.get("patch_applied_paths")
    if not isinstance(applied_paths, list):
        applied_paths = []

    restored = ExecutionState(
        proposal_digest=_optional_str(raw.get("proposal_digest")),
        backup_branch=_optional_str(raw.get("backup_branch")),
        backup_commit=_optional_str(raw.get("backup_commit")),
        diff_previewed_paths=[_normalize_path(item) for item in paths if _normalize_path(item)],
        patch_applied=bool(raw.get("patch_applied")),
        patch_applied_paths=[
            _normalize_path(item) for item in applied_paths if _normalize_path(item)
        ],
    )
    _execution_state.set(restored)


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_path(path: str) -> str:
    return str(path or "").strip().replace("\\", "/")


def compute_proposal_digest(text: str) -> str:
    payload = str(text or "").strip()
    if not payload:
        return ""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _clear_mutation_milestones(state: ExecutionState) -> None:
    state.backup_branch = None
    state.backup_commit = None
    state.diff_previewed_paths = []
    state.patch_applied = False
    state.patch_applied_paths = []


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


def _backup_matches_persisted(state: ExecutionState) -> bool:
    if not state.backup_branch or not state.backup_commit:
        return False

    persisted_branch = get_backup_branch()
    persisted_commit = get_backup_commit()
    if not persisted_branch or not persisted_commit:
        return False

    return (
        state.backup_branch == persisted_branch
        and state.backup_commit == persisted_commit
    )


def update_from_tool_result(action: str, args: dict[str, Any] | None, result: str) -> None:
    if not is_execution_state_dedup_enabled():
        return

    state = get_execution_state()
    text = str(result or "")

    if action == "propose_code_changes":
        if PROPOSAL_MARKER not in text:
            return

        digest = compute_proposal_digest(text)
        if not digest:
            return

        if state.proposal_digest and state.proposal_digest != digest:
            _clear_mutation_milestones(state)

        state.proposal_digest = digest
        return

    if action == "generate_unified_diff":
        if "diff" not in text.lower() and "Diff" not in text:
            return

        paths = _extract_patch_paths(args)
        if not paths:
            return

        merged = list(state.diff_previewed_paths)
        for path in paths:
            if path and path not in merged:
                merged.append(path)
        state.diff_previewed_paths = merged
        return

    if action == "git_create_backup":
        if not _is_success_marker(text, BACKUP_SUCCESS_MARKER):
            return

        branch = get_backup_branch()
        commit = get_backup_commit()
        if not branch or not commit:
            return

        state.backup_branch = branch
        state.backup_commit = commit
        return

    if action in {"apply_patch", "write_repo_file"}:
        marker = PATCH_SUCCESS_MARKER if action == "apply_patch" else WRITE_SUCCESS_MARKER
        if not _is_success_marker(text, marker):
            return

        paths = _extract_patch_paths(args)
        if action == "write_repo_file":
            single = _normalize_path(str((args or {}).get("path") or ""))
            paths = [single] if single else paths

        if not paths:
            return

        state.patch_applied = True
        state.patch_applied_paths = paths
        return


def should_skip_tool(action: str, args: dict[str, Any] | None) -> str | None:
    if not is_execution_state_dedup_enabled():
        return None

    state = get_execution_state()

    if action == "git_create_backup":
        if not state.backup_branch or state.patch_applied:
            return None

        if not _backup_matches_persisted(state):
            return None

        return (
            "跳过重复 git_create_backup: 当前任务 checkpoint 已记录备份分支 "
            + state.backup_branch
            + "，且 patch 尚未应用。如需重新备份请在追问中明确说明「重新备份」。"
        )

    if action in {"apply_patch", "write_repo_file"}:
        if not state.patch_applied or not state.patch_applied_paths:
            return None

        requested_paths = _extract_patch_paths(args)
        if action == "write_repo_file":
            single = _normalize_path(str((args or {}).get("path") or ""))
            requested_paths = [single] if single else requested_paths

        if sorted(requested_paths) != sorted(state.patch_applied_paths):
            return None

        label = "apply_patch" if action == "apply_patch" else "write_repo_file"
        paths_text = ", ".join(state.patch_applied_paths)
        return (
            "跳过重复 "
            + label
            + ": 当前任务 checkpoint 已记录对这些路径的成功写入 ("
            + paths_text
            + ")。如需再次修改请提交新的修改方案。"
        )

    return None


def user_requests_rebackup(question: str) -> bool:
    text = str(question or "").strip().lower()
    if not text:
        return False

    for keyword in RE_BACKUP_KEYWORDS:
        if keyword.lower() in text:
            return True

    return False


def clear_backup_milestones() -> None:
    state = get_execution_state()
    state.backup_branch = None
    state.backup_commit = None


def build_resume_hint(state: ExecutionState | None = None) -> str:
    if not is_execution_state_dedup_enabled():
        return ""

    current = state or get_execution_state()
    lines = ["[checkpoint] 任务已从 checkpoint 恢复，当前 mutation 里程碑:"]

    if current.proposal_digest:
        lines.append("- 修改方案 digest: " + current.proposal_digest)
    else:
        lines.append("- 修改方案: 无记录")

    if current.backup_branch:
        lines.append(
            "- Git 备份: "
            + current.backup_branch
            + " @ "
            + str(current.backup_commit or "")
        )
    else:
        lines.append("- Git 备份: 尚未完成")

    if current.diff_previewed_paths:
        lines.append(
            "- Diff 已预览: "
            + ", ".join(current.diff_previewed_paths)
        )

    if current.patch_applied:
        lines.append(
            "- Patch/写入: 已完成 ("
            + ", ".join(current.patch_applied_paths)
            + ")"
        )
    else:
        lines.append("- Patch/写入: 尚未完成")

    lines.append(
        "请勿重复 git_create_backup 或 apply_patch/write_repo_file，"
        "除非用户明确要求重新执行或提交了新的修改方案。"
    )
    return "\n".join(lines)


def apply_milestone_token(
    token: MilestoneToken,
    *,
    tool: str,
    args: dict[str, Any] | None,
    details: dict[str, Any] | None,
) -> None:
    """Structured milestone mirror (PR-M2) — called only from advance_from_outcome."""
    payload = dict(details or {})
    state = get_execution_state()

    if token == MilestoneToken.PROPOSED:
        digest = str(payload.get("proposal_digest") or "").strip() or None
        if not digest:
            return
        if state.proposal_digest and state.proposal_digest != digest:
            _clear_mutation_milestones(state)
        state.proposal_digest = digest
        return

    if token == MilestoneToken.DIFF_GENERATED:
        paths = payload.get("paths")
        if not isinstance(paths, list):
            paths = _extract_patch_paths(args)
        if not paths:
            return
        merged = list(state.diff_previewed_paths)
        for path in paths:
            normalized = _normalize_path(str(path))
            if normalized and normalized not in merged:
                merged.append(normalized)
        state.diff_previewed_paths = merged
        return

    if token == MilestoneToken.BACKUP_CREATED:
        branch = str(payload.get("backup_branch") or get_backup_branch() or "").strip()
        commit = str(payload.get("backup_commit") or get_backup_commit() or "").strip()
        if not branch or not commit:
            return
        state.backup_branch = branch
        state.backup_commit = commit
        return

    if token in {MilestoneToken.PATCH_APPLIED, MilestoneToken.FILE_WRITTEN}:
        paths = payload.get("paths")
        if not isinstance(paths, list):
            paths = _extract_patch_paths(args)
        if tool == "write_repo_file":
            single = _normalize_path(str((args or {}).get("path") or ""))
            paths = [single] if single else paths
        if not paths:
            return
        state.patch_applied = True
        state.patch_applied_paths = [_normalize_path(str(item)) for item in paths if _normalize_path(str(item))]
        return
