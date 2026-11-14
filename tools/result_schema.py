"""Structured tool reject schema (v0.9 PR-S1)."""

from __future__ import annotations

import logging
from typing import Any, Literal, TypedDict

import config.settings as settings

logger = logging.getLogger(__name__)

REJECT_CODE_MUTATION_FSM_BLOCKED = "mutation_fsm_blocked"
REJECT_CODE_TOOL_NOT_ALLOWED = "tool_not_allowed"
REJECT_CODE_CONFIRM_REJECTED = "confirm_rejected"
REJECT_CODE_VALIDATION_ERROR = "validation_error"
REJECT_CODE_TOOL_NOT_FOUND = "tool_not_found"

FSM_REJECT_PREFIX = "Mutation workflow blocked:"
CONFIRM_REJECT_PREFIX = "用户已取消执行工具:"
VALIDATION_ERROR_PREFIX = "参数错误:"
UNKNOWN_TOOL_MESSAGE = "不存在的工具"


class ToolRejectResult(TypedDict):
    ok: Literal[False]
    code: str
    message: str
    details: dict[str, Any]


ToolResult = str | ToolRejectResult


def is_structured_tool_reject_enabled() -> bool:
    return settings.STRUCTURED_TOOL_REJECT_ENABLED


def is_tool_reject(result: ToolResult) -> bool:
    return isinstance(result, dict) and result.get("ok") is False


def tool_reject(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> ToolRejectResult:
    return {
        "ok": False,
        "code": code,
        "message": message,
        "details": dict(details or {}),
    }


def finalize_tool_result(result: ToolResult) -> ToolResult:
    if is_tool_reject(result) and not is_structured_tool_reject_enabled():
        return result["message"]
    return result


def tool_result_message(result: ToolResult) -> str:
    if is_tool_reject(result):
        return result["message"]
    try:
        from tools.outcome_schema import is_tool_success

        if is_tool_success(result):
            return result["message"]
    except Exception as e:
        logger.warning("tool_result_message 异常: %s", e, exc_info=True)
        pass
    return str(result)


def format_tool_result_for_display(result: ToolResult) -> str:
    try:
        from tools.outcome_schema import format_outcome_for_display, is_tool_success

        if is_tool_success(result) or is_tool_reject(result):
            return format_outcome_for_display(result)
    except Exception as e:
        logger.warning("format_tool_result_for_display 异常: %s", e, exc_info=True)
        pass
    return tool_result_message(result)


def format_tool_result_for_memory(result: ToolResult) -> str:
    try:
        from tools.outcome_schema import format_outcome_for_memory, is_tool_success

        if is_tool_success(result) or is_tool_reject(result):
            return format_outcome_for_memory(result)
    except Exception as e:
        logger.warning("format_tool_result_for_memory 异常: %s", e, exc_info=True)
        pass
    return tool_result_message(result)


def tool_result_audit_fields(result: ToolResult) -> tuple[str, str | None, dict[str, Any] | None]:
    try:
        from tools.outcome_schema import extract_outcome_audit_fields, is_tool_success

        if is_tool_success(result) or is_tool_reject(result):
            text, reject_code, details, success_code, milestone = extract_outcome_audit_fields(result)
            if is_tool_reject(result) and not is_structured_tool_reject_enabled():
                return text, None, None
            merged = dict(details or {})
            if success_code:
                merged["success_code"] = success_code
            if milestone:
                merged["milestone"] = milestone
            audit_code = reject_code if is_tool_reject(result) else success_code
            return text, audit_code, merged or None
    except Exception as e:
        logger.warning("tool_result_audit_fields 异常: %s", e, exc_info=True)
        pass
    text = tool_result_message(result)
    if not is_tool_reject(result):
        return text, None, None

    details = dict(result.get("details") or {})
    if is_structured_tool_reject_enabled():
        return text, result["code"], details

    return text, None, None


def is_tool_result_error(result: ToolResult) -> bool:
    try:
        from tools.outcome_schema import is_outcome_error, is_tool_success

        if is_tool_success(result) or is_tool_reject(result):
            return is_outcome_error(result)
    except Exception as e:
        logger.warning("is_tool_result_error 异常: %s", e, exc_info=True)
        pass

    if is_tool_reject(result):
        return True

    text = str(result or "")
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
