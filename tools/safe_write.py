from pathlib import Path

from audit.audit_log import write_audit_event
from config.settings import (
    MAX_WRITE_BYTES,
    WRITABLE_EXTENSIONS,
)
from context.tms.backup import has_task_backup_record
from context.tms.types import MilestoneToken
from security.path_guard import (
    is_blocked_file,
    path_has_ignored_segment,
    resolve_repo_path,
)
from tools.outcome_schema import SUCCESS_CODE_FILE_WRITTEN, tool_success



def _is_writable_extension(path: Path):

    suffix = path.suffix.lower()


    if suffix == "":

        return False


    return suffix in WRITABLE_EXTENSIONS



def _has_backup_record():

    return has_task_backup_record(audit=False)



def validate_write_target(path):

    if path is None or not str(path).strip():

        return None, "写入路径不能为空"


    relative_path = str(path).strip().replace("\\", "/")


    try:

        target = resolve_repo_path(relative_path)

    except ValueError as e:

        return None, str(e)


    if path_has_ignored_segment(relative_path):

        return None, "拒绝写入忽略目录下的文件: " + relative_path


    if is_blocked_file(target):

        return None, "拒绝写入敏感文件: " + target.name


    if not _is_writable_extension(target):

        return None, "文件类型不在可写范围内: " + target.name


    if target.exists() and target.is_dir():

        return None, "目标是目录，不能写入: " + relative_path


    parent = target.parent


    if not parent.exists():

        return None, "父目录不存在，当前不支持自动创建目录: " + str(parent)


    if not parent.is_dir():

        return None, "父路径无效: " + str(parent)


    return target, None



def write_repo_file(
    path,
    content,
):

    if content is None:

        return "写入内容不能为空"


    target, error = validate_write_target(path)


    if error:

        return error


    try:

        encoded = content.encode("utf-8")

    except UnicodeEncodeError:

        return "写入内容不是合法 UTF-8 文本"


    byte_count = len(encoded)


    if byte_count > MAX_WRITE_BYTES:

        return (
            "写入内容过大: "
            + str(byte_count)
            + " 字节，上限 "
            + str(MAX_WRITE_BYTES)
            + " 字节"
        )


    created = not target.exists()

    relative_path = str(
        target.relative_to(resolve_repo_path())
    ).replace("\\", "/")


    has_backup = _has_backup_record()


    target.write_text(
        content,
        encoding="utf-8",
    )


    write_audit_event({

        "event":
        "file_write",

        "path":
        relative_path,

        "bytes":
        byte_count,

        "created":
        created,

        "status":
        "success",

        "backup_present":
        has_backup,

        "warning":
        None
        if has_backup
        else "no_backup_record",

    })


    lines = []


    if not has_backup:

        lines.append(
            "警告: 当前没有 Git 备份记录，建议先调用 git_create_backup。"
        )


    lines.extend([

        "文件写入完成",

        "路径: "
        + relative_path,

        "操作: "
        + ("新建" if created else "覆盖"),

        "字节数: "
        + str(byte_count),

        "备份状态: "
        + ("已有备份记录" if has_backup else "无备份记录（已允许写入）"),

    ])


    message = "\n".join(lines)

    return tool_success(
        SUCCESS_CODE_FILE_WRITTEN,
        message,
        milestone=MilestoneToken.FILE_WRITTEN,
        details={
            "paths": [relative_path],
            "backup_present": has_backup,
        },
    )
