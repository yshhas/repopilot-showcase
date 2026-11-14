from config.agent_mode import AGENT_MODE_READONLY
from storage.task_store import TASK_STATUS_COMPLETED, TASK_STATUS_FAILED
from tests.live_llm.assertions import (
    assert_audit_has_task_start,
    assert_backup_before_apply,
    assert_file_contains,
    assert_no_mutation_tools,
    assert_no_unsafe_paths_in_events,
    assert_report_generated,
    assert_step_count_within_limit,
    assert_successful_tool_call,
    assert_task_completed,
    assert_tool_confirmed,
    assert_tools_allowed,
    assert_tools_include_any,
    count_agent_loop_steps,
    evaluate_live_case,
    extract_successful_tool_calls,
)


def _sample_events(task_id="live1"):
    return [
        {
            "event": "react_step",
            "task_id": task_id,
            "step": "task_start",
            "details": {"question": "hello"},
        },
        {
            "event": "tool_call",
            "task_id": task_id,
            "tool": "list_repo_files",
            "args": {"path": "tools", "extensions": ".py"},
            "result": "ok",
            "status": "success",
        },
        {
            "event": "react_step",
            "task_id": task_id,
            "step": "finish",
            "details": {"answer": "done"},
        },
    ]


def test_count_agent_loop_steps_ignores_checkpoint_events():
    events = [
        {"event": "react_step", "step": "task_start"},
        {"event": "react_step", "step": "ai_output"},
        {"event": "react_step", "step": "tool_request"},
        {"event": "react_step", "step": "tool_result"},
        {"event": "react_step", "step": "checkpoint_saved"},
        {"event": "react_step", "step": "checkpoint_skipped"},
        {"event": "react_step", "step": "ai_output"},
        {"event": "react_step", "step": "finish"},
    ]

    assert count_agent_loop_steps(events) == 2


def test_assert_step_count_within_limit_ignores_internal_events():
    events = [
        {"event": "react_step", "step": "task_start"},
        {"event": "react_step", "step": "ai_output"},
        {"event": "react_step", "step": "tool_request"},
        {"event": "react_step", "step": "tool_result"},
        {"event": "react_step", "step": "checkpoint_saved"},
        {"event": "react_step", "step": "ai_output"},
        {"event": "react_step", "step": "finish"},
    ]

    assert_step_count_within_limit(events, max_steps=2)


def test_extract_successful_tool_calls_ignores_errors():
    events = [
        {
            "event": "tool_call",
            "tool": "apply_patch",
            "status": "error",
        },
        {
            "event": "tool_call",
            "tool": "git_status",
            "status": "success",
        },
    ]

    assert extract_successful_tool_calls(events) == ["git_status"]


def test_assert_no_mutation_tools_passes_for_readonly_chain():
    assert_no_mutation_tools(["list_repo_files", "search_in_repo"])


def test_assert_no_mutation_tools_fails_for_apply_patch():
    try:
        assert_no_mutation_tools(["generate_unified_diff", "apply_patch"])
    except AssertionError as exc:
        assert "apply_patch" in str(exc)
    else:
        raise AssertionError("expected assertion failure")


def test_assert_backup_before_apply_requires_backup():
    assert_backup_before_apply(
        ["generate_unified_diff", "git_create_backup", "apply_patch"]
    )

    try:
        assert_backup_before_apply(["apply_patch"])
    except AssertionError as exc:
        assert "git_create_backup" in str(exc)
    else:
        raise AssertionError("expected assertion failure")


def test_assert_tools_allowed_readonly_blocks_backup():
    try:
        assert_tools_allowed(["git_create_backup"], AGENT_MODE_READONLY)
    except AssertionError as exc:
        assert "git_create_backup" in str(exc)
    else:
        raise AssertionError("expected assertion failure")


def test_assert_tools_include_any():
    assert_tools_include_any(
        ["search_in_repo", "finish"],
        ["search_in_repo", "read_repo_file"],
    )

    try:
        assert_tools_include_any(["git_status"], ["propose_code_changes"])
    except AssertionError as exc:
        assert "propose_code_changes" in str(exc)
    else:
        raise AssertionError("expected assertion failure")


def test_assert_no_unsafe_paths_in_events_blocks_traversal():
    events = [
        {
            "event": "tool_call",
            "tool": "read_repo_file",
            "args": {"path": "../.env"},
            "status": "success",
        }
    ]

    try:
        assert_no_unsafe_paths_in_events(events)
    except AssertionError as exc:
        assert ".env" in str(exc) or ".." in str(exc)
    else:
        raise AssertionError("expected assertion failure")


def test_assert_report_generated():
    task = {
        "status": TASK_STATUS_COMPLETED,
        "agent_mode": AGENT_MODE_READONLY,
        "question": "q",
        "answer": "a",
    }

    report = __import__(
        "audit.task_report",
        fromlist=["build_task_report"],
    ).build_task_report("live-report", _sample_events("live-report"), task_record=task)

    assert_report_generated(report, "live-report")


def test_evaluate_live_case_readonly_fixture():
    task_id = "live-readonly-case"
    task = {
        "status": TASK_STATUS_COMPLETED,
        "agent_mode": AGENT_MODE_READONLY,
        "question": "list files",
        "answer": "done",
    }

    result = evaluate_live_case(
        {
            "id": "readonly_list",
            "mode": "readonly",
            "forbid_mutation_tools": True,
            "require_task_completed": True,
            "max_steps": 12,
        },
        task_id=task_id,
        task=task,
        events=_sample_events(task_id),
    )

    assert result["tool_calls"] == ["list_repo_files"]
    assert "任务审计摘要" in result["report"]


def test_evaluate_live_case_fails_on_incomplete_task():
    task_id = "live-failed-case"
    task = {
        "status": TASK_STATUS_FAILED,
        "agent_mode": AGENT_MODE_READONLY,
        "question": "list files",
    }

    try:
        evaluate_live_case(
            {
                "id": "readonly_list",
                "mode": "readonly",
                "require_task_completed": True,
                "max_steps": 12,
            },
            task_id=task_id,
            task=task,
            events=_sample_events(task_id),
        )
    except AssertionError as exc:
        assert "completed" in str(exc)
    else:
        raise AssertionError("expected assertion failure")


def test_assert_audit_has_task_start():
    assert_audit_has_task_start(_sample_events("audit1"), "audit1")

    try:
        assert_audit_has_task_start(
            [
                {
                    "event": "react_step",
                    "task_id": "missing",
                    "step": "finish",
                }
            ],
            "missing",
        )
    except AssertionError as exc:
        assert "task_start" in str(exc)
    else:
        raise AssertionError("expected assertion failure")


def test_assert_task_completed():
    assert_task_completed({"status": TASK_STATUS_COMPLETED})

    try:
        assert_task_completed({"status": TASK_STATUS_FAILED})
    except AssertionError as exc:
        assert "completed" in str(exc)
    else:
        raise AssertionError("expected assertion failure")


def test_assert_file_contains(tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text("updated content\n", encoding="utf-8")

    assert_file_contains(tmp_path, "sample.txt", "updated")

    try:
        assert_file_contains(tmp_path, "sample.txt", "missing")
    except AssertionError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("expected assertion failure")


def test_assert_successful_tool_call():
    events = [
        {
            "event": "tool_call",
            "tool": "apply_patch",
            "status": "error",
        },
        {
            "event": "tool_call",
            "tool": "apply_patch",
            "status": "success",
        },
    ]

    assert_successful_tool_call(events, "apply_patch")

    try:
        assert_successful_tool_call(events, "git_create_backup")
    except AssertionError as exc:
        assert "git_create_backup" in str(exc)
    else:
        raise AssertionError("expected assertion failure")


def test_assert_tool_confirmed():
    events = [
        {
            "event": "tool_confirmation",
            "tool": "apply_patch",
            "confirmed": True,
        }
    ]

    assert_tool_confirmed(events, "apply_patch")

    try:
        assert_tool_confirmed(events, "write_repo_file")
    except AssertionError as exc:
        assert "write_repo_file" in str(exc)
    else:
        raise AssertionError("expected assertion failure")


def _mutation_case_events(task_id="live-mutation-case"):
    return [
        {
            "event": "react_step",
            "task_id": task_id,
            "step": "task_start",
            "details": {"question": "modify sample.txt"},
        },
        {
            "event": "tool_call",
            "task_id": task_id,
            "tool": "generate_unified_diff",
            "args": {"path": "sample.txt", "new_content": "updated\n"},
            "status": "success",
        },
        {
            "event": "tool_call",
            "task_id": task_id,
            "tool": "git_create_backup",
            "status": "success",
        },
        {
            "event": "tool_confirmation",
            "task_id": task_id,
            "tool": "apply_patch",
            "confirmed": True,
        },
        {
            "event": "tool_call",
            "task_id": task_id,
            "tool": "apply_patch",
            "args": {"path": "sample.txt", "new_content": "updated\n"},
            "status": "success",
        },
        {
            "event": "react_step",
            "task_id": task_id,
            "step": "finish",
            "details": {"answer": "done"},
        },
    ]


def test_evaluate_live_case_mutation_fixture(tmp_path):
    task_id = "live-mutation-case"
    task = {
        "status": TASK_STATUS_COMPLETED,
        "agent_mode": "full",
        "question": "modify sample.txt",
        "answer": "done",
    }

    sample = tmp_path / "sample.txt"
    sample.write_text("updated\n", encoding="utf-8")

    result = evaluate_live_case(
        {
            "id": "full_mutation_sample_txt",
            "mode": "full",
            "require_tools_any": ["apply_patch"],
            "require_tool_confirmation": ["apply_patch"],
            "assert_file_contains": {
                "path": "sample.txt",
                "substring": "updated",
            },
            "require_task_completed": True,
            "max_steps": 16,
        },
        task_id=task_id,
        task=task,
        events=_mutation_case_events(task_id),
        repo_root=tmp_path,
    )

    assert result["tool_calls"] == [
        "generate_unified_diff",
        "git_create_backup",
        "apply_patch",
    ]
