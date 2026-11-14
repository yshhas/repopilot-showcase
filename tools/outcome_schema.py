"""ToolOutcome schema, normalize compat layer, and formatters (PR-M2)."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

import config.settings as settings
from context.tms.types import MilestoneToken, parse_milestone_token
from tools.result_schema import (
    CONFIRM_REJECT_PREFIX,
    FSM_REJECT_PREFIX,
    REJECT_CODE_CONFIRM_REJECTED,
    REJECT_CODE_MUTATION_FSM_BLOCKED,
    REJECT_CODE_TOOL_NOT_ALLOWED,
    REJECT_CODE_TOOL_NOT_FOUND,
    REJECT_CODE_VALIDATION_ERROR,
    UNKNOWN_TOOL_MESSAGE,
    ToolRejectResult,
    VALIDATION_ERROR_PREFIX,
    is_tool_reject,
    tool_reject,
    tool_result_message,
)

SUCCESS_CODE_PROPOSAL_GENERATED = "proposal_generated"
SUCCESS_CODE_DIFF_GENERATED = "diff_generated"
SUCCESS_CODE_BACKUP_CREATED = "backup_created"
SUCCESS_CODE_PATCH_APPLIED = "patch_applied"
SUCCESS_CODE_FILE_WRITTEN = "file_written"
SUCCESS_CODE_ROLLBACK_COMPLETED = "rollback_completed"
SUCCESS_CODE_DEDUP_SKIPPED = "dedup_skipped"
SUCCESS_CODE_VERIFY_PASSED = "verify_passed"
SUCCESS_CODE_VERIFY_FAILED = "verify_failed"
SUCCESS_CODE_VERIFY_SKIPPED = "verify_skipped"
SUCCESS_CODE_LEGACY_STRING = "legacy_string"

MUTATION_TOOLS = frozenset({
    "propose_code_changes",
    "generate_unified_diff",
    "git_create_backup",
    "apply_patch",
    "write_repo_file",
    "git_rollback",
})

# Deprecated frozen table — do not extend (removed in M5).
_LEGACY_MARKER_RULES: dict[str, tuple[str, MilestoneToken]] = {
    "propose_code_changes": ("修改方案", MilestoneToken.PROPOSED),
    "git_create_backup": ("Git 备份完成", MilestoneToken.BACKUP_CREATED),
    "apply_patch": ("Patch 应用完成", MilestoneToken.PATCH_APPLIED),
    "write_repo_file": ("文件写入完成", MilestoneToken.FILE_WRITTEN),
    "git_rollback": ("Git 回滚完成", MilestoneToken.ROLLBACK_TO_BACKUP),
}


class ToolSuccessResult(TypedDict):
    ok: Literal[True]
    code: str
    message: str
    milestone: str | None
    details: dict[str, Any]


ToolOutcome = ToolSuccessResult | ToolRejectResult
LegacyRawResult = str | ToolOutcome


def is_tool_success(result: ToolOutcome | str) -> bool:
    return isinstance(result, dict) and result.get("ok") is True


def tool_success(
    code: str,
    message: str,
    *,
    milestone: MilestoneToken | str | None = None,
    details: dict[str, Any] | None = None,
) -> ToolSuccessResult:
    milestone_value = None
    if milestone is not None:
        token = (
            milestone
            if isinstance(milestone, MilestoneToken)
            else parse_milestone_token(milestone)
        )
        if token is None:
            raise ValueError("invalid milestone token: " + repr(milestone))
        milestone_value = token.value

    return {
        "ok": True,
        "code": code,
        "message": message,
        "milestone": milestone_value,
        "details": dict(details or {}),
    }


def _extract_patch_paths(args: dict[str, Any] | None) -> list[str]:
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


def _legacy_diff_milestone(text: str, args: dict[str, Any] | None) -> MilestoneToken | None:
    if "diff" not in text.lower() and "Diff" not in text:
        return None
    if not _extract_patch_paths(args):
        return None
    return MilestoneToken.DIFF_GENERATED


def _classify_error_string(text: str) -> ToolRejectResult | None:
    if text == UNKNOWN_TOOL_MESSAGE:
        return tool_reject(REJECT_CODE_TOOL_NOT_FOUND, text, details={})
    if text.startswith(VALIDATION_ERROR_PREFIX):
        return tool_reject(REJECT_CODE_VALIDATION_ERROR, text, details={})
    if text.startswith(FSM_REJECT_PREFIX):
        return tool_reject(REJECT_CODE_MUTATION_FSM_BLOCKED, text, details={})
    if text.startswith(CONFIRM_REJECT_PREFIX):
        return tool_reject(REJECT_CODE_CONFIRM_REJECTED, text, details={})
    if text.startswith("工具 ") and " 模式下不可用" in text:
        return tool_reject(REJECT_CODE_TOOL_NOT_ALLOWED, text, details={})
    return None


def _legacy_marker_to_outcome(
    tool: str,
    text: str,
    args: dict[str, Any] | None,
) -> ToolSuccessResult | None:
    if tool not in MUTATION_TOOLS:
        return None

    if tool == "generate_unified_diff":
        token = _legacy_diff_milestone(text, args)
        if token is None:
            return None
        return tool_success(
            SUCCESS_CODE_DIFF_GENERATED,
            text,
            milestone=token,
            details={"paths": _extract_patch_paths(args), "legacy_normalized": True},
        )

    rule = _LEGACY_MARKER_RULES.get(tool)
    if rule is None:
        return None

    marker, token = rule
    if marker not in text:
        return None

    code_map = {
        MilestoneToken.PROPOSED: SUCCESS_CODE_PROPOSAL_GENERATED,
        MilestoneToken.BACKUP_CREATED: SUCCESS_CODE_BACKUP_CREATED,
        MilestoneToken.PATCH_APPLIED: SUCCESS_CODE_PATCH_APPLIED,
        MilestoneToken.FILE_WRITTEN: SUCCESS_CODE_FILE_WRITTEN,
        MilestoneToken.ROLLBACK_TO_BACKUP: SUCCESS_CODE_ROLLBACK_COMPLETED,
    }

    details: dict[str, Any] = {"legacy_normalized": True}
    if token == MilestoneToken.PROPOSED:
        from context.execution_state import compute_proposal_digest

        digest = compute_proposal_digest(text)
        if digest:
            details["proposal_digest"] = digest
    if token in {MilestoneToken.PATCH_APPLIED, MilestoneToken.FILE_WRITTEN, MilestoneToken.DIFF_GENERATED}:
        paths = _extract_patch_paths(args)
        if paths:
            details["paths"] = paths

    return tool_success(
        code_map.get(token, SUCCESS_CODE_LEGACY_STRING),
        text,
        milestone=token,
        details=details,
    )


def normalize_tool_outcome(
    raw: LegacyRawResult,
    *,
    tool: str,
    args: dict[str, Any] | None = None,
) -> ToolOutcome:
    if is_tool_reject(raw):
        return raw

    if is_tool_success(raw):
        token = parse_milestone_token(raw.get("milestone"))
        if raw.get("milestone") and token is None:
            return tool_reject(
                "invalid_milestone_token",
                "Invalid milestone token: " + str(raw.get("milestone")),
                details={"tool": tool, "milestone": raw.get("milestone")},
            )
        return raw

    text = str(raw or "")
    reject = _classify_error_string(text)
    if reject is not None:
        return reject

    if text.startswith("跳过重复"):
        return tool_success(
            SUCCESS_CODE_DEDUP_SKIPPED,
            text,
            milestone=None,
            details={"tool": tool},
        )

    legacy = _legacy_marker_to_outcome(tool, text, args)
    if legacy is not None:
        return legacy

    return tool_success(
        SUCCESS_CODE_LEGACY_STRING,
        text,
        milestone=None,
        details={"tool": tool},
    )


def finalize_tool_outcome(outcome: ToolOutcome) -> ToolOutcome | str:
    if is_tool_reject(outcome) and not settings.STRUCTURED_TOOL_REJECT_ENABLED:
        return outcome["message"]
    return outcome


def format_outcome_for_display(outcome: ToolOutcome | str) -> str:
    return tool_result_message(outcome)


def format_outcome_for_memory(outcome: ToolOutcome | str) -> str:
    if getattr(settings, "MEMORY_STRUCTURED_TOOL_RESULT_ENABLED", False) and is_tool_success(
        outcome
    ):
        import json

        return json.dumps(
            {
                "ok": True,
                "code": outcome["code"],
                "milestone": outcome.get("milestone"),
                "message": outcome["message"],
            },
            ensure_ascii=False,
        )
    return tool_result_message(outcome)


def extract_outcome_audit_fields(
    outcome: ToolOutcome | str,
) -> tuple[str, str | None, dict[str, Any] | None, str | None, str | None]:
    text = tool_result_message(outcome)

    if is_tool_reject(outcome):
        details = dict(outcome.get("details") or {})
        code = outcome["code"]
        if settings.STRUCTURED_TOOL_REJECT_ENABLED:
            return text, code, details, None, None
        return text, None, None, None, None

    if is_tool_success(outcome):
        details = dict(outcome.get("details") or {})
        return (
            text,
            None,
            details or None,
            outcome.get("code"),
            outcome.get("milestone"),
        )

    return text, None, None, None, None


def is_outcome_error(outcome: ToolOutcome | str) -> bool:
    if is_tool_reject(outcome):
        return True
    text = str(outcome or "")
    if text == UNKNOWN_TOOL_MESSAGE:
        return True
    if text.startswith(VALIDATION_ERROR_PREFIX):
        return True
    if text.startswith(FSM_REJECT_PREFIX):
        return True
    if text.startswith(CONFIRM_REJECT_PREFIX):
        return True
    if text.startswith("工具 ") and " 模式下不可用" in text:
        return True
    return False
