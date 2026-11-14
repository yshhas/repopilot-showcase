"""Post-mutation verification tool (v0.10.2) — minimal syntax + patched-file checks."""

from __future__ import annotations

import ast
from typing import Any

from audit.audit_log import write_audit_event
from context.tms.context import get_shadow
from context.tms.types import VerificationSlice, VerificationStatus
from security.path_guard import is_blocked_file, resolve_repo_path
from tools.outcome_schema import tool_success

SUCCESS_CODE_VERIFY_PASSED = "verify_passed"
SUCCESS_CODE_VERIFY_FAILED = "verify_failed"
SUCCESS_CODE_VERIFY_SKIPPED = "verify_skipped"

DEFAULT_CHECKS = ("patched_files", "syntax")
SUPPORTED_CHECKS = frozenset(DEFAULT_CHECKS)


def _parse_csv(value: str | None) -> list[str]:
    if value is None:
        return []
    parts = []
    for item in str(value).replace(";", ",").split(","):
        text = item.strip().replace("\\", "/")
        if text:
            parts.append(text)
    return parts


def _resolve_paths(paths_arg: str, artifacts_paths: list[str]) -> list[str]:
    explicit = _parse_csv(paths_arg)
    if explicit:
        return explicit
    return [str(item).strip().replace("\\", "/") for item in artifacts_paths if str(item).strip()]


def _parse_checks(checks_arg: str) -> list[str]:
    requested = _parse_csv(checks_arg) if str(checks_arg or "").strip() else list(DEFAULT_CHECKS)
    ordered: list[str] = []
    for name in requested:
        key = name.lower()
        if key in SUPPORTED_CHECKS and key not in ordered:
            ordered.append(key)
    return ordered or list(DEFAULT_CHECKS)


def _check_patched_files(paths: list[str]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for relative in paths:
        try:
            target = resolve_repo_path(relative)
        except ValueError as exc:
            failures.append(relative + ": " + str(exc))
            continue
        if is_blocked_file(target):
            failures.append(relative + ": blocked sensitive path")
            continue
        if not target.is_file():
            failures.append(relative + ": file missing after patch")
            continue
        try:
            target.read_text(encoding="utf-8")
        except OSError as exc:
            failures.append(relative + ": unreadable (" + str(exc) + ")")
        except UnicodeDecodeError:
            failures.append(relative + ": not valid UTF-8 text")
    return (len(failures) == 0), failures


def _check_syntax(paths: list[str]) -> tuple[bool, list[str], int]:
    """Return ok, failures, skipped_non_python count."""
    failures: list[str] = []
    skipped = 0
    for relative in paths:
        if not relative.lower().endswith(".py"):
            skipped += 1
            continue
        try:
            target = resolve_repo_path(relative)
            source = target.read_text(encoding="utf-8")
            ast.parse(source, filename=relative)
        except ValueError as exc:
            failures.append(relative + ": " + str(exc))
        except OSError as exc:
            failures.append(relative + ": read error (" + str(exc) + ")")
        except SyntaxError as exc:
            failures.append(
                relative
                + ": SyntaxError line "
                + str(exc.lineno)
                + ": "
                + (exc.msg or "invalid syntax")
            )
    return (len(failures) == 0), failures, skipped


def _record_verification(
    *,
    status: VerificationStatus,
    code: str,
    checks_run: list[str],
    failed_checks: list[str],
    paths: list[str],
    message: str,
) -> None:
    state = get_shadow()
    state.verification = VerificationSlice(
        status=status,
        last_code=code,
        checks_run=list(checks_run),
        failed_checks=list(failed_checks),
        paths=list(paths),
        message=message,
    )


def verify_change(checks: str = "patched_files,syntax", paths: str = "") -> Any:
    """Run post-apply checks. Does not advance mutation workflow."""
    shadow = get_shadow()
    target_paths = _resolve_paths(paths, shadow.artifacts.patch_applied_paths)
    check_ids = _parse_checks(checks)

    if not target_paths:
        message = (
            "验证跳过: 无已修改路径（先 apply_patch / write_repo_file，"
            "或传入 paths）"
        )
        _record_verification(
            status=VerificationStatus.SKIPPED,
            code=SUCCESS_CODE_VERIFY_SKIPPED,
            checks_run=check_ids,
            failed_checks=[],
            paths=[],
            message=message,
        )
        write_audit_event(
            {
                "event": "verify_change_result",
                "status": "skipped",
                "code": SUCCESS_CODE_VERIFY_SKIPPED,
                "checks_run": check_ids,
                "paths": [],
                "failed_checks": [],
            }
        )
        return tool_success(
            SUCCESS_CODE_VERIFY_SKIPPED,
            message,
            milestone=None,
            details={
                "checks_run": check_ids,
                "paths": [],
                "failures": [],
                "failed_checks": [],
            },
        )

    failures: list[str] = []
    failed_checks: list[str] = []
    details_checks: dict[str, Any] = {}

    for check_id in check_ids:
        if check_id == "patched_files":
            ok, check_failures = _check_patched_files(target_paths)
            details_checks["patched_files"] = {
                "ok": ok,
                "failures": check_failures,
            }
            if not ok:
                failed_checks.append(check_id)
                failures.extend(check_failures)
        elif check_id == "syntax":
            ok, check_failures, skipped = _check_syntax(target_paths)
            details_checks["syntax"] = {
                "ok": ok,
                "failures": check_failures,
                "skipped_non_python": skipped,
            }
            if not ok:
                failed_checks.append(check_id)
                failures.extend(check_failures)

    if failed_checks:
        message_lines = [
            "验证失败: verify_failed",
            "路径: " + ", ".join(target_paths),
            "失败检查: " + ", ".join(failed_checks),
        ]
        message_lines.extend("- " + item for item in failures[:20])
        message = "\n".join(message_lines)
        _record_verification(
            status=VerificationStatus.FAILED,
            code=SUCCESS_CODE_VERIFY_FAILED,
            checks_run=check_ids,
            failed_checks=failed_checks,
            paths=target_paths,
            message=message,
        )
        write_audit_event(
            {
                "event": "verify_change_result",
                "status": "failed",
                "code": SUCCESS_CODE_VERIFY_FAILED,
                "checks_run": check_ids,
                "paths": target_paths,
                "failed_checks": failed_checks,
                "failures": failures[:20],
            }
        )
        return tool_success(
            SUCCESS_CODE_VERIFY_FAILED,
            message,
            milestone=None,
            details={
                "checks_run": check_ids,
                "paths": target_paths,
                "failures": failures,
                "failed_checks": failed_checks,
                "checks": details_checks,
            },
        )

    message = (
        "验证通过: verify_passed\n"
        "路径: "
        + ", ".join(target_paths)
        + "\n检查: "
        + ", ".join(check_ids)
    )
    _record_verification(
        status=VerificationStatus.PASSED,
        code=SUCCESS_CODE_VERIFY_PASSED,
        checks_run=check_ids,
        failed_checks=[],
        paths=target_paths,
        message=message,
    )
    write_audit_event(
        {
            "event": "verify_change_result",
            "status": "passed",
            "code": SUCCESS_CODE_VERIFY_PASSED,
            "checks_run": check_ids,
            "paths": target_paths,
            "failed_checks": [],
        }
    )
    return tool_success(
        SUCCESS_CODE_VERIFY_PASSED,
        message,
        milestone=None,
        details={
            "checks_run": check_ids,
            "paths": target_paths,
            "failures": [],
            "failed_checks": [],
            "checks": details_checks,
        },
    )
