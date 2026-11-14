import subprocess
from datetime import datetime

from audit.audit_log import write_audit_event
from config.settings import (
    DEFAULT_BACKUP_MESSAGE,
    GIT_BACKUP_BRANCH_PREFIX,
    REPO_ROOT,
)
from context.tms.backup import (
    backup_create_persistence_note,
    maybe_persist_global_backup_dual_write,
    resolve_task_backup_ref,
)
from context.tms.types import MilestoneToken
from tools.outcome_schema import SUCCESS_CODE_BACKUP_CREATED, SUCCESS_CODE_ROLLBACK_COMPLETED, tool_success



def _run_git(args):

    try:

        completed = subprocess.run(

            ["git", *args],

            cwd=str(REPO_ROOT),

            capture_output=True,

            text=True,

            encoding="utf-8",

            errors="replace",

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



def _is_git_repo():

    success, _ = _run_git(["rev-parse", "--is-inside-work-tree"])

    return success



def _has_head_commit():

    success, _ = _run_git(["rev-parse", "HEAD"])

    return success



def git_status():

    if not _is_git_repo():

        return (
            "当前仓库未初始化 Git。\n"
            "请先在项目根目录执行：\n"
            "git init\n"
            "git add .\n"
            'git commit -m "initial commit"'
        )


    lines = ["Git 状态", "仓库: " + str(REPO_ROOT), ""]


    if not _has_head_commit():

        lines.append("当前分支: (尚无 commit)")

        lines.append("")

        lines.append("说明: 需要先完成首次 commit，才能创建备份分支。")

    else:

        success, branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])

        if success:

            lines.append("当前分支: " + branch)


        success, commit = _run_git(["rev-parse", "HEAD"])

        if success:

            lines.append("当前 commit: " + commit)


    success, status = _run_git(["status", "--short"])

    if success:

        lines.append("")

        lines.append("工作区变更:")

        if status:

            lines.append(status)

        else:

            lines.append("(无未提交变更)")


    return "\n".join(lines)



def git_create_backup(
    message=DEFAULT_BACKUP_MESSAGE,
):

    if not _is_git_repo():

        return (
            "无法创建备份：当前仓库未初始化 Git。\n"
            "请先在项目根目录执行：\n"
            "git init\n"
            "git add .\n"
            'git commit -m "initial commit"'
        )


    if not _has_head_commit():

        return (
            "无法创建备份：仓库还没有任何 commit。\n"
            "请先完成首次提交：\n"
            "git add .\n"
            'git commit -m "initial commit"\n'
            "注意：首次 commit 前需配置 Git 用户信息（user.name / user.email）。"
        )


    success, original_branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])


    if not success:

        return "无法获取当前分支: " + original_branch


    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    backup_branch = GIT_BACKUP_BRANCH_PREFIX + "/" + timestamp


    success, create_result = _run_git(["checkout", "-b", backup_branch])


    if not success:

        return "创建备份分支失败: " + create_result


    success, status = _run_git(["status", "--porcelain"])

    committed = False


    if success and status.strip():

        success, add_result = _run_git(["add", "-A"])


        if not success:

            _run_git(["checkout", original_branch])

            return "备份时暂存文件失败: " + add_result


        commit_message = message.strip() or DEFAULT_BACKUP_MESSAGE

        success, commit_result = _run_git(["commit", "-m", commit_message])


        if not success:

            _run_git(["checkout", original_branch])

            if "user.email" in commit_result or "user.name" in commit_result:

                return (
                    "备份 commit 失败：未配置 Git 用户信息。\n"
                    "请先执行：\n"
                    'git config user.email "you@example.com"\n'
                    'git config user.name "Your Name"'
                )


            return "备份 commit 失败: " + commit_result


        committed = True


    success, commit_hash = _run_git(["rev-parse", "HEAD"])


    if not success:

        _run_git(["checkout", original_branch])

        return "无法读取备份 commit: " + commit_hash


    success, checkout_result = _run_git(["checkout", original_branch])


    if not success:

        return (
            "备份已创建，但切回原分支失败，请手动执行: git checkout "
            + original_branch
            + "\n错误: "
            + checkout_result
        )


    maybe_persist_global_backup_dual_write(
        backup_branch=backup_branch,
        backup_commit=commit_hash,
        original_branch=original_branch,
    )

    resolved = resolve_task_backup_ref(audit=False)
    backup_source = resolved.source if resolved else "global_file"

    write_audit_event({

        "event":
        "git_backup",

        "backup_branch":
        backup_branch,

        "backup_commit":
        commit_hash,

        "original_branch":
        original_branch,

        "committed":
        committed,

        "message":
        message,

        "backup_source":
        backup_source,

    })


    lines = [

        "Git 备份完成",

        "仓库: "
        + str(REPO_ROOT),

        "原分支: "
        + original_branch,

        "备份分支: "
        + backup_branch,

        "备份 commit: "
        + commit_hash,

        "是否产生新 commit: "
        + ("是" if committed else "否"),

        "提交说明: "
        + (message.strip() or DEFAULT_BACKUP_MESSAGE),

        "",

        backup_create_persistence_note(),

    ]


    message = "\n".join(lines)

    return tool_success(
        SUCCESS_CODE_BACKUP_CREATED,
        message,
        milestone=MilestoneToken.BACKUP_CREATED,
        details={
            "backup_branch": backup_branch,
            "backup_commit": commit_hash,
            "original_branch": original_branch,
        },
    )


def git_rollback():

    ref = resolve_task_backup_ref()

    if ref is None:

        return (
            "无法回滚：没有可用的备份记录。\n"
            "请先调用 git_create_backup 创建备份，"
            "或检查 logs/last_backup.json 是否存在。"
        )

    backup_branch = ref.backup_branch

    backup_commit = ref.backup_commit

    original_branch = ref.original_branch


    if not _is_git_repo():

        return "无法回滚：当前目录不是 Git 仓库。"


    success, commit_type = _run_git(["cat-file", "-t", backup_commit])


    if not success or commit_type != "commit":

        return (
            "无法回滚：备份 commit 不存在或已失效。\n"
            "备份 commit: "
            + str(backup_commit)
        )


    success, current_branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])


    if not success:

        return "无法获取当前分支: " + current_branch


    target_branch = original_branch or current_branch

    branch_warning = ""


    success, branch_head = _run_git(["rev-parse", "--verify", backup_branch])


    if not success:

        branch_warning = (
            "警告: 备份分支 "
            + backup_branch
            + " 已不存在，将直接使用备份 commit 回滚。\n"
        )

    elif branch_head != backup_commit:

        branch_warning = (
            "警告: 备份分支 HEAD ("
            + branch_head
            + ") 与记录的备份 commit ("
            + backup_commit
            + ") 不一致，将以记录的 commit 为准。\n"
        )


    if current_branch != target_branch:

        success, checkout_result = _run_git(["checkout", target_branch])


        if not success:

            return (
                "切换回原分支失败: "
                + checkout_result
                + "\n目标分支: "
                + target_branch
            )


    success, reset_result = _run_git(["reset", "--hard", backup_commit])


    if not success:

        return "回滚失败: " + reset_result


    write_audit_event({

        "event":
        "git_rollback",

        "backup_branch":
        backup_branch,

        "backup_commit":
        backup_commit,

        "original_branch":
        target_branch,

        "previous_branch":
        current_branch,

        "backup_source":
        ref.source,

    })


    lines = [

        "Git 回滚完成",

        "仓库: "
        + str(REPO_ROOT),

        "回滚目标分支: "
        + target_branch,

        "备份分支: "
        + backup_branch,

        "回滚至 commit: "
        + backup_commit,

        "",

        "说明: 工作区与索引已恢复为备份时的状态，备份分支仍保留。",

    ]


    if branch_warning:

        lines.insert(1, branch_warning.rstrip())

    message = "\n".join(lines)

    return tool_success(
        SUCCESS_CODE_ROLLBACK_COMPLETED,
        message,
        milestone=MilestoneToken.ROLLBACK_TO_BACKUP,
        details={
            "backup_branch": backup_branch,
            "backup_commit": backup_commit,
            "original_branch": target_branch,
        },
    )
