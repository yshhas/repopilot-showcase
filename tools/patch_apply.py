"""Apply unified diff patches via git apply (v0.4 diff MVP — S2)."""

from __future__ import annotations

import subprocess

import config.settings as settings
from audit.audit_log import write_audit_event
from context.tms.backup import has_task_backup_record, resolve_task_backup_ref
from context.tms.types import MilestoneToken
from schemas import FileChange, normalize_to_changes
from security.path_guard import resolve_repo_path
from tools.outcome_schema import SUCCESS_CODE_PATCH_APPLIED, tool_success
from tools.diff_engine import (
    _format_paths_for_display,
    build_batch_diff,
    build_unified_diff,
    normalize_new_content,
    read_repo_text_for_diff,
    summarize_diff,
    validate_diff_text,
)


def _has_backup_record() -> bool:
    return has_task_backup_record(audit=False)


def _backup_audit_fields() -> dict[str, str]:
    ref = resolve_task_backup_ref(audit=False)
    if ref is None:
        return {}
    return {
        "backup_branch": ref.backup_branch,
        "backup_commit": ref.backup_commit,
        "backup_source": ref.source,
    }


def _backup_requirement_error() -> str | None:
    if not settings.PATCH_REQUIRE_BACKUP:
        return None

    if not _has_backup_record():
        return (
            "无法应用 patch：没有可用的 Git 备份记录。\n"
            "请先调用 git_create_backup，或检查 logs/last_backup.json。"
        )

    return None


def _run_git(args: list[str], *, input_text: str | None = None) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(settings.REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            input=input_text,
        )

        output = (completed.stdout or "").strip()

        error = (completed.stderr or "").strip()

        if completed.returncode != 0:
            detail = error or output or "Git 命令执行失败"

            return False, detail

        return True, output

    except FileNotFoundError:
        return False, "未找到 git 命令，请先安装 Git 并加入 PATH"

    except Exception as e:
        return False, "执行 Git 命令失败: " + str(e)


def _empty_stats() -> dict:
    return {
        "hunk_count": 0,
        "lines_added": 0,
        "lines_removed": 0,
        "changed_lines": 0,
    }


def _audit_patch_apply(
    relative_path: str,
    status: str,
    *,
    error: str | None = None,
    byte_count: int | None = None,
    created: bool | None = None,
    has_backup: bool | None = None,
    stats: dict | None = None,
) -> None:
    event: dict = {
        "event": "patch_apply",
        "path": relative_path,
        "status": status,
        "engine_version": settings.DIFF_ENGINE_VERSION,
    }

    if error is not None:
        event["error"] = error

    if byte_count is not None:
        event["bytes"] = byte_count

    if created is not None:
        event["created"] = created

    if has_backup is not None:
        event["backup_present"] = has_backup

        if has_backup:
            event.update(_backup_audit_fields())

    if stats is not None:
        event["hunk_count"] = stats.get("hunk_count", 0)
        event["lines_added"] = stats.get("lines_added", 0)
        event["lines_removed"] = stats.get("lines_removed", 0)
        event["changed_lines"] = stats.get("changed_lines", 0)

    write_audit_event(event)


def _audit_patch_apply_batch(
    paths: list[str],
    status: str,
    *,
    error: str | None = None,
    failed_path: str | None = None,
    has_backup: bool | None = None,
    stats: dict | None = None,
) -> None:
    event: dict = {
        "event": "patch_apply",
        "path": paths[0],
        "file_count": len(paths),
        "paths": _format_paths_for_display(paths),
        "status": status,
        "engine_version": settings.DIFF_ENGINE_VERSION,
    }

    if error is not None:
        event["error"] = error

    if failed_path is not None:
        event["failed_path"] = failed_path

    if has_backup is not None:
        event["backup_present"] = has_backup

        if has_backup:
            event.update(_backup_audit_fields())

    if stats is not None:
        event["hunk_count"] = stats.get("hunk_count", 0)
        event["lines_added"] = stats.get("lines_added", 0)
        event["lines_removed"] = stats.get("lines_removed", 0)
        event["changed_lines"] = stats.get("changed_lines", 0)

    write_audit_event(event)


def apply_repo_patch(path: str, new_content: str) -> str:
    relative_path = str(path).strip().replace("\\", "/")

    if not relative_path:
        return "路径不能为空"

    old_text, read_error = read_repo_text_for_diff(relative_path)

    if read_error:
        return read_error

    if new_content is None:
        return "写入内容不能为空"

    try:
        new_text = normalize_new_content(new_content)
    except ValueError as e:
        return str(e)

    try:
        encoded = new_text.encode("utf-8")
    except UnicodeEncodeError:
        return "写入内容不是合法 UTF-8 文本"

    byte_count = len(encoded)

    if byte_count > settings.MAX_WRITE_BYTES:
        return (
            "写入内容过大: "
            + str(byte_count)
            + " 字节，上限 "
            + str(settings.MAX_WRITE_BYTES)
            + " 字节"
        )

    diff = build_unified_diff(relative_path, old_text, new_text)

    validation = validate_diff_text(
        diff,
        path=relative_path,
        old_text=old_text,
        new_text=new_text,
    )

    if not validation.ok:
        return validation.error

    stats = summarize_diff(diff)

    backup_error = _backup_requirement_error()

    if backup_error:
        _audit_patch_apply(
            relative_path,
            "failed",
            error=backup_error,
            byte_count=byte_count,
            has_backup=False,
            stats=stats,
        )

        return backup_error

    has_backup = _has_backup_record()

    success, detail = _run_git(["rev-parse", "--is-inside-work-tree"])

    if not success:
        message = "无法应用 patch：当前目录不是 Git 仓库。"

        _audit_patch_apply(
            relative_path,
            "failed",
            error=message,
            byte_count=byte_count,
            has_backup=has_backup,
            stats=stats,
        )

        return message

    success, detail = _run_git(["apply", "--check", "-"], input_text=diff)

    if not success:
        message = "patch 预检失败 (git apply --check): " + detail

        _audit_patch_apply(
            relative_path,
            "failed",
            error=message,
            byte_count=byte_count,
            has_backup=has_backup,
            stats=stats,
        )

        return message

    success, detail = _run_git(["apply", "-"], input_text=diff)

    if not success:
        message = "patch 应用失败: " + detail

        _audit_patch_apply(
            relative_path,
            "failed",
            error=message,
            byte_count=byte_count,
            has_backup=has_backup,
            stats=stats,
        )

        return message

    target = resolve_repo_path(relative_path)

    try:
        applied_text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        message = "patch 已应用，但读取结果文件失败: " + str(e)

        _audit_patch_apply(
            relative_path,
            "failed",
            error=message,
            byte_count=byte_count,
            has_backup=has_backup,
            stats=stats,
        )

        return message

    if applied_text != new_text:
        message = (
            "patch 已应用，但文件内容与预期不一致，请检查工作区状态。"
        )

        _audit_patch_apply(
            relative_path,
            "failed",
            error=message,
            byte_count=byte_count,
            has_backup=has_backup,
            stats=stats,
        )

        return message

    created = old_text == ""

    _audit_patch_apply(
        relative_path,
        "success",
        byte_count=byte_count,
        created=created,
        has_backup=has_backup,
        stats=stats,
    )

    lines: list[str] = []

    if not has_backup:
        lines.append(
            "警告: 当前没有 Git 备份记录，建议先调用 git_create_backup。"
        )

    lines.extend(
        [
            "Patch 应用完成",
            "路径: " + relative_path,
            "操作: " + ("新建" if old_text == "" else "修改"),
            "字节数: " + str(byte_count),
            "变更: +"
            + str(stats["lines_added"])
            + " / -"
            + str(stats["lines_removed"])
            + " 行",
            "备份状态: "
            + ("已有备份记录" if has_backup else "无备份记录"),
        ]
    )

    return tool_success(
        SUCCESS_CODE_PATCH_APPLIED,
        "\n".join(lines),
        milestone=MilestoneToken.PATCH_APPLIED,
        details={"paths": [relative_path]},
    )


def apply_repo_patch_batch(changes: list[FileChange]) -> str:
    paths = [change.path for change in changes]
    build_result = build_batch_diff(changes)

    if not build_result.ok:
        _audit_patch_apply_batch(
            paths,
            "failed",
            error=build_result.error,
            failed_path=build_result.failed_path,
            stats=build_result.total_stats or _empty_stats(),
        )
        return build_result.error

    combined_diff = build_result.combined_diff
    total_stats = build_result.total_stats or _empty_stats()
    per_file_new_text = build_result.per_file_new_text or {}

    backup_error = _backup_requirement_error()

    if backup_error:
        _audit_patch_apply_batch(
            paths,
            "failed",
            error=backup_error,
            has_backup=False,
            stats=total_stats,
        )

        return backup_error

    has_backup = _has_backup_record()

    success, detail = _run_git(["rev-parse", "--is-inside-work-tree"])

    if not success:
        message = "无法应用 patch：当前目录不是 Git 仓库。"

        _audit_patch_apply_batch(
            paths,
            "failed",
            error=message,
            has_backup=has_backup,
            stats=total_stats,
        )

        return message

    success, detail = _run_git(["apply", "--check", "-"], input_text=combined_diff)

    if not success:
        message = "patch 预检失败 (git apply --check): " + detail

        _audit_patch_apply_batch(
            paths,
            "failed",
            error=message,
            has_backup=has_backup,
            stats=total_stats,
        )

        return message

    success, detail = _run_git(["apply", "-"], input_text=combined_diff)

    if not success:
        message = "patch 应用失败: " + detail

        _audit_patch_apply_batch(
            paths,
            "failed",
            error=message,
            has_backup=has_backup,
            stats=total_stats,
        )

        return message

    for relative_path in paths:
        expected_text = per_file_new_text[relative_path]
        target = resolve_repo_path(relative_path)

        try:
            applied_text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            message = (
                "patch 已应用，但读取结果文件失败 ("
                + relative_path
                + "): "
                + str(e)
            )

            _audit_patch_apply_batch(
                paths,
                "failed",
                error=message,
                failed_path=relative_path,
                has_backup=has_backup,
                stats=total_stats,
            )

            return message

        if applied_text != expected_text:
            message = (
                "patch 已应用，但文件内容与预期不一致 ("
                + relative_path
                + ")，请检查工作区状态。"
            )

            _audit_patch_apply_batch(
                paths,
                "failed",
                error=message,
                failed_path=relative_path,
                has_backup=has_backup,
                stats=total_stats,
            )

            return message

    _audit_patch_apply_batch(
        paths,
        "success",
        has_backup=has_backup,
        stats=total_stats,
    )

    lines: list[str] = []

    if not has_backup:
        lines.append(
            "警告: 当前没有 Git 备份记录，建议先调用 git_create_backup。"
        )

    lines.extend(
        [
            "Patch 批量应用完成",
            "文件数: " + str(len(paths)),
            "路径: " + _format_paths_for_display(paths),
            "变更: +"
            + str(total_stats["lines_added"])
            + " / -"
            + str(total_stats["lines_removed"])
            + " 行",
            "Hunk 数: " + str(total_stats["hunk_count"]),
            "备份状态: "
            + ("已有备份记录" if has_backup else "无备份记录"),
        ]
    )

    return tool_success(
        SUCCESS_CODE_PATCH_APPLIED,
        "\n".join(lines),
        milestone=MilestoneToken.PATCH_APPLIED,
        details={"paths": list(paths)},
    )


def apply_patch(
    path: str | None = None,
    new_content: str | None = None,
    changes: list | None = None,
) -> str:
    normalized, error = normalize_to_changes(
        path=path,
        new_content=new_content,
        changes=changes,
    )

    if error:
        return error

    if len(normalized) == 1:
        change = normalized[0]
        return apply_repo_patch(change.path, change.new_content)

    return apply_repo_patch_batch(normalized)
