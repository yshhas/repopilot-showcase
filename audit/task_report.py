import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from config.settings import AUDIT_LOG_FILE
from storage.task_store import get_task


def load_events_for_task(
    task_id,
    audit_file=None,
):

    path = Path(audit_file or AUDIT_LOG_FILE)

    if not path.is_file():

        return []


    events = []


    with open(
        path,
        encoding="utf-8",
    ) as f:

        for line in f:

            line = line.strip()


            if not line:

                continue


            try:

                record = json.loads(line)

            except json.JSONDecodeError:

                continue


            if not isinstance(record, dict):

                continue


            if record.get("task_id") != task_id:

                continue


            events.append(record)


    return events



def _parse_time(value):

    if not value:

        return None


    try:

        return datetime.fromisoformat(value)

    except ValueError:

        return None



def _format_duration(seconds):

    if seconds < 1:

        return f"{seconds * 1000:.0f} 毫秒"


    if seconds < 60:

        return f"{seconds:.1f} 秒"


    minutes = int(seconds // 60)

    remain = seconds % 60

    return f"{minutes} 分 {remain:.0f} 秒"



def _summarize_react_step(event):

    step = event.get("step", "")

    details = event.get("details") or {}


    if step == "task_start":

        return f"任务开始: {details.get('question', '')}"


    if step == "user_followup":

        return f"用户追问: {details.get('question', '')}"


    if step == "tool_request":

        return (
            "请求工具: "
            + str(details.get("action", ""))
        )


    if step == "tool_result":

        return (
            "工具返回: "
            + str(details.get("action", ""))
        )


    if step == "finish":

        return (
            "任务完成: "
            + str(details.get("answer", ""))
        )


    if step == "plain_answer":

        return (
            "直接回答: "
            + str(details.get("answer", ""))
        )


    if step == "max_steps_reached":

        return (
            "达到最大步数: "
            + str(details.get("limit", ""))
        )


    if step == "checkpoint_saved":

        checkpoint_id = str(details.get("checkpoint_id", ""))

        if len(checkpoint_id) > 8:

            checkpoint_id = checkpoint_id[:8] + "..."

        return (
            "Checkpoint 保存 · step "
            + str(details.get("react_step", ""))
            + " · id "
            + checkpoint_id
        )


    if step == "task_cancelled":

        return (
            "任务取消 · step "
            + str(details.get("react_step", ""))
        )


    if step == "task_resumed":

        return (
            "任务恢复 · 从 step "
            + str(details.get("react_step", ""))
            + " 继续"
        )


    if step == "cancel_requested":

        react_step = details.get("react_step")

        if react_step is not None:

            return (
                "Cancel 请求 · step "
                + str(react_step)
            )

        return "Cancel 请求"


    if step == "ai_output":

        response = str(details.get("response", ""))

        preview = response.replace("\n", " ")


        if len(preview) > 80:

            preview = preview[:80] + "..."

        return "AI 输出: " + preview


    return step



def _is_batch_event(event) -> bool:
    file_count = event.get("file_count")

    return isinstance(file_count, int) and file_count > 1


def _batch_paths_label(event) -> str:
    paths = event.get("paths")

    if paths:
        return str(paths)

    return str(event.get("path", ""))


def _batch_failed_path_suffix(event) -> str:
    failed_path = event.get("failed_path")

    if not failed_path:
        return ""

    return " · failed_path=" + str(failed_path)


def _summarize_diff_preview(event):
    if _is_batch_event(event):
        file_count = event.get("file_count", 0)
        paths = _batch_paths_label(event)

        if event.get("status") != "success":
            return (
                "Diff batch 失败 ("
                + str(file_count)
                + " files): "
                + paths
                + _batch_failed_path_suffix(event)
                + " · "
                + str(event.get("error", "unknown"))
            )

        return (
            "Diff batch ("
            + str(file_count)
            + " files): "
            + paths
            + " · +"
            + str(event.get("lines_added", 0))
            + " / -"
            + str(event.get("lines_removed", 0))
            + " · "
            + str(event.get("hunk_count", 0))
            + " hunks"
        )

    path = str(event.get("path", ""))

    if event.get("status") != "success":

        return (
            "Diff 预览失败 "
            + path
            + ": "
            + str(event.get("error", "unknown"))
        )

    return (
        "Diff 预览 "
        + path
        + ": +"
        + str(event.get("lines_added", 0))
        + " / -"
        + str(event.get("lines_removed", 0))
        + " 行, "
        + str(event.get("hunk_count", 0))
        + " hunks"
    )


def _summarize_patch_apply(event):
    if _is_batch_event(event):
        file_count = event.get("file_count", 0)
        paths = _batch_paths_label(event)

        if event.get("status") != "success":
            return (
                "Patch batch 失败 ("
                + str(file_count)
                + " files): "
                + paths
                + _batch_failed_path_suffix(event)
                + " · "
                + str(event.get("error", "unknown"))
            )

        backup_label = "有备份" if event.get("backup_present") else "无备份"

        backup_branch = event.get("backup_branch")

        if backup_branch:

            backup_label += " (" + str(backup_branch) + ")"

        return (
            "Patch batch ("
            + str(file_count)
            + " files): "
            + paths
            + " · +"
            + str(event.get("lines_added", 0))
            + " / -"
            + str(event.get("lines_removed", 0))
            + " · success · "
            + backup_label
        )

    path = str(event.get("path", ""))

    if event.get("status") != "success":

        return (
            "Patch 应用失败 "
            + path
            + ": "
            + str(event.get("error", "unknown"))
        )

    action = "新建" if event.get("created") else "修改"

    backup_label = "有备份" if event.get("backup_present") else "无备份"

    backup_branch = event.get("backup_branch")

    if backup_branch:

        backup_label += " (" + str(backup_branch) + ")"

    return (
        "Patch 应用成功 ("
        + action
        + ") "
        + path
        + ": +"
        + str(event.get("lines_added", 0))
        + " / -"
        + str(event.get("lines_removed", 0))
        + " 行, "
        + backup_label
    )


def _summarize_special_event(event):

    event_type = event.get("event", "")


    if event_type == "file_write":

        action = "创建" if event.get("created") else "覆盖"

        return (
            f"{action}文件 {event.get('path', '')} "
            f"({event.get('bytes', 0)} 字节)"
        )


    if event_type == "git_backup":

        return (
            "Git 备份: "
            + str(event.get("backup_branch", ""))
            + " @ "
            + str(event.get("backup_commit", ""))[:8]
        )


    if event_type == "git_rollback":

        return (
            "Git 回滚至 "
            + str(event.get("backup_commit", ""))[:8]
        )


    if event_type == "change_proposal":

        files = event.get("files") or []

        return (
            "修改方案: "
            + str(event.get("summary", ""))
            + f" ({len(files)} 个文件)"
        )


    if event_type == "tool_confirmation":

        confirmed = "已确认" if event.get("confirmed") else "已取消"

        return (
            f"工具确认 ({confirmed}): "
            + str(event.get("tool", ""))
        )


    if event_type == "diff_preview":

        return _summarize_diff_preview(event)


    if event_type == "patch_apply":

        return _summarize_patch_apply(event)


    return None



def build_task_report(
    task_id,
    events,
    task_record=None,
):

    lines = [
        "===== 任务审计摘要 =====",
        "任务 ID: " + task_id,
    ]


    if task_record:

        lines.extend([
            "状态: " + str(task_record.get("status", "")),
            "模式: " + str(task_record.get("agent_mode", "full")),
            "问题: " + str(task_record.get("question", "")),
        ])

        answer = task_record.get("answer")

        if answer:

            lines.append("回答: " + str(answer))


    if not events:

        lines.extend([
            "",
            "未找到该 task_id 的审计记录。",
            "请确认 logs/audit.jsonl 中存在对应事件。",
            "===== 报告结束 =====",
        ])

        return "\n".join(lines)


    times = [
        parsed
        for parsed in (
            _parse_time(event.get("time"))
            for event in events
        )
        if parsed is not None
    ]


    if times:

        start = min(times)

        end = max(times)

        duration = (end - start).total_seconds()

        lines.extend([
            "",
            "时间范围: "
            + start.isoformat()
            + " ~ "
            + end.isoformat(),
            "耗时: "
            + _format_duration(duration),
        ])


    lines.append("审计事件数: " + str(len(events)))


    event_counts = Counter(
        event.get("event", "unknown")
        for event in events
    )


    lines.extend([
        "",
        "--- 事件统计 ---",
    ])


    for name, count in sorted(event_counts.items()):

        lines.append(f"{name}: {count}")


    react_steps = [
        event
        for event in events
        if event.get("event") == "react_step"
    ]


    if react_steps:

        lines.extend([
            "",
            "--- ReAct 流程 ---",
        ])


        for index, event in enumerate(react_steps, start=1):

            time_label = event.get("time", "")

            summary = _summarize_react_step(event)

            lines.append(
                f"{index}. [{time_label}] {summary}"
            )


    tool_calls = [
        event
        for event in events
        if event.get("event") == "tool_call"
    ]


    if tool_calls:

        lines.extend([
            "",
            "--- 工具调用 ---",
        ])


        tool_stats = {}


        for event in tool_calls:

            tool = event.get("tool", "unknown")

            if tool not in tool_stats:

                tool_stats[tool] = {
                    "total": 0,
                    "success": 0,
                    "error": 0,
                    "duration_ms": 0.0,
                }


            stats = tool_stats[tool]

            stats["total"] += 1

            stats["duration_ms"] += float(
                event.get("duration_ms") or 0
            )


            if event.get("status") == "error":

                stats["error"] += 1

            else:

                stats["success"] += 1


        for tool, stats in sorted(tool_stats.items()):

            lines.append(
                f"- {tool}: "
                f"调用 {stats['total']} 次, "
                f"成功 {stats['success']}, "
                f"失败 {stats['error']}, "
                f"耗时 {stats['duration_ms']:.2f} ms"
            )


    special_events = []


    for event in events:

        event_type = event.get("event", "")


        if event_type in {
            "file_write",
            "git_backup",
            "git_rollback",
            "change_proposal",
            "tool_confirmation",
            "diff_preview",
            "patch_apply",
        }:

            special_events.append(event)


    lines.extend([
        "",
        "--- 写入 / Diff / Patch / Git / 确认 ---",
    ])


    if special_events:

        for event in special_events:

            summary = _summarize_special_event(event)

            lines.append(
                f"- [{event.get('time', '')}] {summary}"
            )

    else:

        lines.append("(无)")


    lines.append("")
    lines.append("===== 报告结束 =====")


    return "\n".join(lines)



def generate_task_report(
    task_id,
    audit_file=None,
    include_task_record=True,
):

    events = load_events_for_task(
        task_id,
        audit_file=audit_file,
    )

    task_record = None


    if include_task_record:

        task_record = get_task(task_id)


    return build_task_report(
        task_id,
        events,
        task_record=task_record,
    )



if __name__ == "__main__":

    import sys


    if len(sys.argv) < 2:

        print(
            "用法: python -m audit.task_report <task_id>"
        )

        sys.exit(1)


    print(
        generate_task_report(sys.argv[1])
    )
