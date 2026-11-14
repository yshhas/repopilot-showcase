import json
from datetime import datetime, timezone
from typing import Any

from config.settings import AUDIT_LOG_FILE, AUDIT_MAX_FIELD_LENGTH, LOG_DIR
from audit.context import get_task_id, publish_stream_event
from audit.logger import get_logger
from security.redaction import redact_data


logger = get_logger("repopilot.audit")

# Persistent file handle for buffered audit writes (avoids open/close per event).
_audit_file = None
_audit_file_path = None


def _get_audit_file():
    global _audit_file, _audit_file_path
    current_path = str(AUDIT_LOG_FILE)
    if _audit_file is not None and _audit_file_path != current_path:
        _audit_file.close()
        _audit_file = None
        _audit_file_path = None
    if _audit_file is None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        _audit_file = open(AUDIT_LOG_FILE, "a", encoding="utf-8", buffering=1)
        _audit_file_path = current_path
    return _audit_file


def _truncate(value: Any):
    from context._shared import truncate_text

    return truncate_text(str(value), AUDIT_MAX_FIELD_LENGTH)



def _sanitize(data: Any):

    return _truncate_values(redact_data(data))


def _truncate_values(data: Any):

    if isinstance(data, dict):

        return {
            key: _truncate_values(value)
            for key, value in data.items()
        }

    if isinstance(data, list):

        return [
            _truncate_values(item)
            for item in data
        ]

    return _truncate(data)



def write_audit_event(event: dict):

    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


    record = {

        "time":
        datetime.now(timezone.utc).isoformat(),

        **event,

    }


    task_id = get_task_id()


    if task_id and "task_id" not in record:

        record["task_id"] = task_id


    line = json.dumps(
        record,
        ensure_ascii=False,
    )


    _get_audit_file().write(line + "\n")


    logger.info(
        "audit event recorded",
        extra={
            "extra_fields": {
                "event": record.get("event"),
                "task_id": record.get("task_id"),
            }
        },
    )


    publish_stream_event(record)



def log_tool_call(
    tool,
    args,
    result,
    duration_ms,
    task_id=None,
):
    from tools.outcome_schema import (
        extract_outcome_audit_fields,
        is_outcome_error,
        is_tool_success,
    )
    from tools.result_schema import is_tool_reject, tool_result_audit_fields

    if is_tool_success(result) or is_tool_reject(result):
        result_text, reject_code, details, success_code, milestone = extract_outcome_audit_fields(
            result
        )
        status = "error" if is_outcome_error(result) else "success"
    else:
        result_text, reject_code, details = tool_result_audit_fields(result)
        success_code = None
        milestone = None
        from tools.result_schema import is_tool_result_error

        status = "error" if is_tool_result_error(result) else "success"

    event = {
        "event": "tool_call",
        "task_id": task_id or get_task_id(),
        "tool": tool,
        "args": _sanitize(args),
        "result": _sanitize(result_text),
        "duration_ms": round(duration_ms, 2),
        "status": status,
    }

    if reject_code is not None:
        event["reject_code"] = reject_code
        event["reject_details"] = _sanitize(details)

    if success_code is not None:
        event["success_code"] = success_code

    if milestone is not None:
        event["milestone"] = milestone

    if details and success_code is not None:
        event["outcome_details"] = _sanitize(details)

    write_audit_event(event)



def log_react_step(
    step,
    task_id=None,
    **details,
):

    write_audit_event({

        "event":
        "react_step",

        "task_id":
        task_id or get_task_id(),

        "step":
        step,

        "details":
        _sanitize(details),

    })
