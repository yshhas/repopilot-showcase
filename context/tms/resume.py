"""TMS resume UX helpers (PR-M5-d / PR-M5-f)."""

from __future__ import annotations

import config.settings as settings
from context.tms.context import get_shadow

RE_BACKUP_KEYWORDS = (
    "重新备份",
    "re-backup",
    "rebackup",
    "redo backup",
    "backup again",
)


def user_requests_rebackup(question: str) -> bool:
    text = str(question or "").strip().lower()
    if not text:
        return False

    for keyword in RE_BACKUP_KEYWORDS:
        if keyword.lower() in text:
            return True

    return False


def clear_tms_backup_milestones() -> None:
    """Clear TMS backup artifact so dedup allows a fresh git_create_backup."""
    state = get_shadow()
    state.artifacts.backup = None


def build_tms_resume_hint() -> str:
    """Resume hint from TMS shadow — used after hydrate without legacy mirror."""
    if not settings.EXECUTION_STATE_DEDUP_ENABLED:
        return ""

    shadow = get_shadow()
    workflow = shadow.workflow
    artifacts = shadow.artifacts

    lines = ["[checkpoint] 任务已从 checkpoint 恢复，当前 mutation 里程碑:"]

    if workflow.proposal_digest:
        lines.append("- 修改方案 digest: " + workflow.proposal_digest)
    else:
        lines.append("- 修改方案: 无记录")

    backup = artifacts.backup
    if backup and backup.backup_branch:
        lines.append(
            "- Git 备份: "
            + backup.backup_branch
            + " @ "
            + str(backup.backup_commit or "")
        )
    else:
        lines.append("- Git 备份: 尚未完成")

    if artifacts.diff_previewed_paths:
        lines.append(
            "- Diff 已预览: "
            + ", ".join(artifacts.diff_previewed_paths)
        )

    if artifacts.patch_applied:
        lines.append(
            "- Patch/写入: 已完成 ("
            + ", ".join(artifacts.patch_applied_paths)
            + ")"
        )
    else:
        lines.append("- Patch/写入: 尚未完成")

    lines.append(
        "请勿重复 git_create_backup 或 apply_patch/write_repo_file，"
        "除非用户明确要求重新执行或提交了新的修改方案。"
    )
    return "\n".join(lines)
