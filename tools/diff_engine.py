"""Unified diff generation and validation (v0.4 diff MVP — S1)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path

import config.settings as settings
from audit.audit_log import write_audit_event
from config.settings import WRITABLE_EXTENSIONS
from context.tms.types import MilestoneToken
from schemas import FileChange, normalize_to_changes
from security.path_guard import (
    is_allowed_extension,
    is_blocked_file,
    is_ignored_dir,
    path_has_ignored_segment,
    resolve_repo_path,
)
from tools.outcome_schema import SUCCESS_CODE_DIFF_GENERATED, tool_success


_HUNK_HEADER = re.compile(r"^@@ ", re.MULTILINE)


@dataclass(frozen=True)
class DiffValidationResult:
    ok: bool
    error: str = ""


@dataclass
class BatchDiffResult:
    ok: bool
    combined_diff: str = ""
    per_file_stats: dict[str, dict] | None = None
    total_stats: dict | None = None
    errors: list[str] | None = None
    failed_path: str | None = None


@dataclass
class BatchBuildResult:
    ok: bool
    combined_diff: str = ""
    per_file_stats: dict[str, dict] | None = None
    total_stats: dict | None = None
    per_file_new_text: dict[str, str] | None = None
    per_file_old_text: dict[str, str] | None = None
    paths: list[str] | None = None
    error: str = ""
    failed_path: str | None = None


def normalize_new_content(content: str) -> str:
    if content is None:
        raise ValueError("写入内容不能为空")

    text = str(content).replace("\r\n", "\n").replace("\r", "\n")

    return text


def _split_lines_for_diff(text: str) -> list[str]:
    normalized = normalize_new_content(text)

    if normalized == "":

        return []

    lines = normalized.splitlines(keepends=True)

    if lines and not lines[-1].endswith("\n"):

        lines[-1] = lines[-1] + "\n"

    return lines


def build_unified_diff(relative_path: str, old_text: str, new_text: str) -> str:
    rel = str(relative_path).strip().replace("\\", "/")

    if not rel:

        raise ValueError("路径不能为空")

    old_lines = _split_lines_for_diff(old_text)

    new_lines = _split_lines_for_diff(new_text)

    diff_lines = unified_diff(
        old_lines,
        new_lines,
        fromfile="a/" + rel,
        tofile="b/" + rel,
        lineterm="\n",
    )

    return "".join(diff_lines)


def _count_diff_stats(diff: str) -> dict:
    lines_added = 0

    lines_removed = 0

    hunk_count = len(_HUNK_HEADER.findall(diff))

    for line in diff.splitlines():

        if line.startswith("+++") or line.startswith("---"):

            continue

        if line.startswith("+"):

            lines_added += 1

        elif line.startswith("-"):

            lines_removed += 1

    return {
        "hunk_count": hunk_count,
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "changed_lines": lines_added + lines_removed,
    }


def validate_diff_text(
    diff: str,
    *,
    path: str,
    old_text: str,
    new_text: str,
    check_changed_lines: bool = True,
) -> DiffValidationResult:
    rel = str(path).strip().replace("\\", "/")

    if not rel:

        return DiffValidationResult(False, "路径不能为空")

    if not diff or not diff.strip():

        return DiffValidationResult(False, "diff 为空：文件内容无变化")

    expected = build_unified_diff(rel, old_text, new_text)

    if diff != expected:

        return DiffValidationResult(False, "diff 与 path/new_content 不一致，请重新生成")

    stats = _count_diff_stats(diff)

    if stats["hunk_count"] == 0:

        return DiffValidationResult(False, "diff 未包含有效 hunk")

    if stats["hunk_count"] > settings.PATCH_MAX_HUNKS:

        return DiffValidationResult(
            False,
            "hunk 数量超过上限: "
            + str(stats["hunk_count"])
            + " > "
            + str(settings.PATCH_MAX_HUNKS),
        )

    if check_changed_lines and stats["changed_lines"] > settings.PATCH_MAX_CHANGED_LINES:

        return DiffValidationResult(
            False,
            "变更行数超过上限: "
            + str(stats["changed_lines"])
            + " > "
            + str(settings.PATCH_MAX_CHANGED_LINES),
        )

    header_old = "--- a/" + rel

    header_new = "+++ b/" + rel

    if header_old not in diff or header_new not in diff:

        return DiffValidationResult(False, "diff 文件头与目标路径不匹配")

    return DiffValidationResult(True, "")


def summarize_diff(diff: str) -> dict:
    stats = _count_diff_stats(diff)

    preview_lines = diff.splitlines()[: settings.PATCH_PREVIEW_MAX_LINES]

    return {
        **stats,
        "preview": "\n".join(preview_lines),
    }


def _validate_diff_path(relative_path: str) -> tuple[Path | None, str | None]:
    if relative_path is None or not str(relative_path).strip():

        return None, "路径不能为空"

    rel = str(relative_path).strip().replace("\\", "/")

    if path_has_ignored_segment(rel):

        return None, "拒绝访问忽略目录下的路径: " + rel

    for part in Path(rel).parts:

        if is_ignored_dir(part):

            return None, "拒绝访问忽略目录下的路径: " + rel

    try:

        target = resolve_repo_path(rel)

    except ValueError as e:

        return None, str(e)

    if target.is_dir():

        return None, "目标是目录，不能作为 patch 路径: " + rel

    if target.exists() and is_blocked_file(target):

        return None, "拒绝访问敏感文件: " + target.name

    suffix = target.suffix.lower()

    if target.exists():

        if not is_allowed_extension(target):

            return None, "文件类型不在允许范围内: " + target.name

    else:

        if suffix == "" or suffix not in WRITABLE_EXTENSIONS:

            return None, "文件类型不在可写范围内: " + rel

        parent = target.parent

        if not parent.exists():

            return None, "父目录不存在，当前不支持自动创建目录: " + str(parent)

        if not parent.is_dir():

            return None, "父路径无效: " + str(parent)

    return target, None


def _audit_diff_preview(
    relative_path: str,
    stats: dict,
    *,
    status: str = "success",
    error: str | None = None,
) -> None:
    event: dict = {
        "event": "diff_preview",
        "path": relative_path,
        "status": status,
        "hunk_count": stats.get("hunk_count", 0),
        "lines_added": stats.get("lines_added", 0),
        "lines_removed": stats.get("lines_removed", 0),
        "changed_lines": stats.get("changed_lines", 0),
        "engine_version": settings.DIFF_ENGINE_VERSION,
    }

    if error is not None:
        event["error"] = error

    write_audit_event(event)


def _check_new_content_size(new_text: str) -> str | None:
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

    return None


def _format_paths_for_display(paths: list[str]) -> str:
    from context._shared import format_paths_summary
    return format_paths_summary(paths)


def _format_paths_for_audit(paths: list[str]) -> str:
    from context._shared import format_paths_summary
    return format_paths_summary(paths)


def _audit_diff_preview_batch(
    paths: list[str],
    stats: dict,
    *,
    status: str = "success",
    error: str | None = None,
    failed_path: str | None = None,
) -> None:
    event: dict = {
        "event": "diff_preview",
        "path": paths[0],
        "file_count": len(paths),
        "paths": _format_paths_for_audit(paths),
        "status": status,
        "hunk_count": stats.get("hunk_count", 0),
        "lines_added": stats.get("lines_added", 0),
        "lines_removed": stats.get("lines_removed", 0),
        "changed_lines": stats.get("changed_lines", 0),
        "engine_version": settings.DIFF_ENGINE_VERSION,
    }

    if error is not None:
        event["error"] = error

    if failed_path is not None:
        event["failed_path"] = failed_path

    write_audit_event(event)


def _sum_stats(per_file_stats: dict[str, dict]) -> dict:
    total = {
        "hunk_count": 0,
        "lines_added": 0,
        "lines_removed": 0,
        "changed_lines": 0,
    }

    for stats in per_file_stats.values():
        total["hunk_count"] += stats.get("hunk_count", 0)
        total["lines_added"] += stats.get("lines_added", 0)
        total["lines_removed"] += stats.get("lines_removed", 0)
        total["changed_lines"] += stats.get("changed_lines", 0)

    return total


def build_batch_diff(changes: list[FileChange]) -> BatchBuildResult:
    paths = [change.path for change in changes]
    combined_parts: list[str] = []
    per_file_stats: dict[str, dict] = {}
    per_file_new_text: dict[str, str] = {}
    per_file_old_text: dict[str, str] = {}

    for change in changes:
        relative_path = change.path

        old_text, read_error = read_repo_text_for_diff(relative_path)

        if read_error:
            return BatchBuildResult(
                ok=False,
                paths=paths,
                error=read_error,
                failed_path=relative_path,
            )

        try:
            new_text = normalize_new_content(change.new_content)
        except ValueError as e:
            return BatchBuildResult(
                ok=False,
                paths=paths,
                error=str(e),
                failed_path=relative_path,
            )

        size_error = _check_new_content_size(new_text)

        if size_error:
            return BatchBuildResult(
                ok=False,
                paths=paths,
                error=size_error,
                failed_path=relative_path,
            )

        diff = build_unified_diff(relative_path, old_text, new_text)

        validation = validate_diff_text(
            diff,
            path=relative_path,
            old_text=old_text,
            new_text=new_text,
            check_changed_lines=False,
        )

        if not validation.ok:
            return BatchBuildResult(
                ok=False,
                paths=paths,
                error=validation.error,
                failed_path=relative_path,
            )

        per_file_stats[relative_path] = _count_diff_stats(diff)
        per_file_new_text[relative_path] = new_text
        per_file_old_text[relative_path] = old_text
        combined_parts.append(diff)

    total_stats = _sum_stats(per_file_stats)

    if total_stats["changed_lines"] > settings.PATCH_MAX_CHANGED_LINES:
        return BatchBuildResult(
            ok=False,
            paths=paths,
            total_stats=total_stats,
            error=(
                "变更行数超过上限: "
                + str(total_stats["changed_lines"])
                + " > "
                + str(settings.PATCH_MAX_CHANGED_LINES)
            ),
        )

    return BatchBuildResult(
        ok=True,
        combined_diff="".join(combined_parts),
        per_file_stats=per_file_stats,
        total_stats=total_stats,
        per_file_new_text=per_file_new_text,
        per_file_old_text=per_file_old_text,
        paths=paths,
    )


def preview_unified_diff_batch(changes: list[FileChange]) -> str:
    if not changes:
        return "参数错误: 需要提供 path + new_content 或 changes"

    paths = [change.path for change in changes]
    empty_stats = {
        "hunk_count": 0,
        "lines_added": 0,
        "lines_removed": 0,
        "changed_lines": 0,
    }

    build_result = build_batch_diff(changes)

    if not build_result.ok:
        _audit_diff_preview_batch(
            paths,
            build_result.total_stats or empty_stats,
            status="failed",
            error=build_result.error,
            failed_path=build_result.failed_path,
        )
        return build_result.error

    combined_diff = build_result.combined_diff
    total_stats = build_result.total_stats or empty_stats
    preview_stats = summarize_diff(combined_diff)

    _audit_diff_preview_batch(paths, total_stats)

    lines = [
        "Unified diff 批量预览",
        "文件数: " + str(len(changes)),
        "路径: " + _format_paths_for_display(paths),
        "变更: +"
        + str(total_stats["lines_added"])
        + " / -"
        + str(total_stats["lines_removed"])
        + " 行",
        "Hunk 数: " + str(total_stats["hunk_count"]),
        "",
        preview_stats["preview"],
    ]

    total_lines = len(combined_diff.splitlines())

    if total_lines > settings.PATCH_PREVIEW_MAX_LINES:
        lines.append("")
        lines.append(
            "(预览已截断，完整 diff 共 "
            + str(total_lines)
            + " 行)"
        )

    return tool_success(
        SUCCESS_CODE_DIFF_GENERATED,
        "\n".join(lines),
        milestone=MilestoneToken.DIFF_GENERATED,
        details={"paths": list(paths)},
    )


def preview_unified_diff(path: str, new_content: str) -> str:
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

    size_error = _check_new_content_size(new_text)

    if size_error:
        return size_error

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

    _audit_diff_preview(relative_path, stats)

    lines = [
        "Unified diff 预览",
        "路径: " + relative_path,
        "变更: +"
        + str(stats["lines_added"])
        + " / -"
        + str(stats["lines_removed"])
        + " 行",
        "Hunk 数: " + str(stats["hunk_count"]),
        "",
        stats["preview"],
    ]

    total_lines = len(diff.splitlines())

    if total_lines > settings.PATCH_PREVIEW_MAX_LINES:
        lines.append("")
        lines.append(
            "(预览已截断，完整 diff 共 "
            + str(total_lines)
            + " 行)"
        )

    return tool_success(
        SUCCESS_CODE_DIFF_GENERATED,
        "\n".join(lines),
        milestone=MilestoneToken.DIFF_GENERATED,
        details={"paths": [relative_path]},
    )


def generate_unified_diff(
    path: str | None = None,
    new_content: str | None = None,
    changes: list[dict] | list[FileChange] | None = None,
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
        return preview_unified_diff(change.path, change.new_content)

    return preview_unified_diff_batch(normalized)


def read_repo_text_for_diff(path: str) -> tuple[str | None, str | None]:
    target, error = _validate_diff_path(path)

    if error:

        return None, error

    if not target.is_file():

        return "", None

    try:

        return target.read_text(encoding="utf-8"), None

    except UnicodeDecodeError:

        return None, "文件不是 UTF-8 文本，暂不支持 diff: " + str(path)
