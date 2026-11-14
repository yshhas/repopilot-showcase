from config.settings import AUDIT_MAX_FIELD_LENGTH, CONFIRM_REQUIRED_TOOLS
from audit.audit_log import write_audit_event
from context._shared import format_paths_summary, truncate_text
import logging

logger = logging.getLogger(__name__)


def _format_changes_for_confirm(changes: list) -> str:
    paths: list[str] = []
    summaries: list[str] = []

    for item in changes:
        if isinstance(item, dict):
            path = str(item.get("path", "")).strip()
            content = str(item.get("new_content", ""))
        else:
            path = str(getattr(item, "path", "")).strip()
            content = str(getattr(item, "new_content", ""))

        paths.append(path)
        summaries.append(path + ": " + truncate_text(content, 200))

    return (
        "files("
        + str(len(paths))
        + ") "
        + format_paths_summary(paths)
        + " | "
        + "; ".join(summaries)
    )


def _format_confirm_args(action, args):

    if not isinstance(args, dict):

        return str(args)


    display = {}


    for key, value in args.items():

        if key == "changes" and isinstance(value, list):
            display["changes"] = _format_changes_for_confirm(value)
            continue

        text = str(value)


        if key in ("content", "new_content") and len(text) > 200:

            text = text[:200] + "...[truncated]"


        display[key] = text


    return display



def request_tool_confirmation(
    action,
    args,
    confirm_callback=None,
):

    if action not in CONFIRM_REQUIRED_TOOLS:

        return True


    display_args = _format_confirm_args(action, args)


    if confirm_callback is not None:

        confirmed = confirm_callback(action, display_args)

    else:

        print("\n=== 工具执行确认 ===")

        print("工具:", action)

        print("参数:", display_args)

        import sys

        sys.stdout.flush()

        answer = input("确认执行？输入 y 继续，其他键取消: ").strip().lower()

        confirmed = answer in ("y", "yes")
        logger.info("工具确认(action=%s, confirmed=%s)", action, confirmed)


    write_audit_event({

        "event":
        "tool_confirmation",

        "tool":
        action,

        "confirmed":
        confirmed,

        "args":
        _truncate_confirm_args(display_args),

    })


    return confirmed



def _truncate_confirm_args(args):

    if not isinstance(args, dict):

        text = str(args)


        if len(text) > AUDIT_MAX_FIELD_LENGTH:

            return text[:AUDIT_MAX_FIELD_LENGTH] + "...[truncated]"


        return text


    truncated = {}


    for key, value in args.items():

        text = str(value)


        if len(text) > AUDIT_MAX_FIELD_LENGTH:

            text = text[:AUDIT_MAX_FIELD_LENGTH] + "...[truncated]"


        truncated[key] = text


    return truncated
