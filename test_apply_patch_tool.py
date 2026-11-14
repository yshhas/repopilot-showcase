import json

import pytest

from audit.context import (
    reset_agent_mode,
    reset_skip_tool_confirm,
    set_agent_mode,
    set_skip_tool_confirm,
)
from config.agent_mode import AGENT_MODE_FULL, AGENT_MODE_READONLY, MUTATION_TOOLS
from config.settings import CONFIRM_REQUIRED_TOOLS
from tools.git_tools import git_create_backup
from tools.result_schema import tool_result_message
from tools.tool_manager import TOOLS, get_react_tools, run_tool


@pytest.fixture(autouse=True)
def _disable_fsm_for_apply_patch_unit_tests(disable_mutation_fsm):
    """Tool unit tests call apply/backup without full propose→diff chain."""
    return disable_mutation_fsm


def test_apply_patch_registered_as_mutation_react_tool():
    tool = TOOLS["apply_patch"]

    assert tool["react"] is True

    assert "apply_patch" in MUTATION_TOOLS

    assert tool["args_model"].__name__ == "ApplyPatchArgs"


def test_apply_patch_in_confirm_required_tools():
    assert "apply_patch" in CONFIRM_REQUIRED_TOOLS


def test_apply_patch_visible_in_full_not_readonly():
    full_tools = get_react_tools(AGENT_MODE_FULL)

    readonly_tools = get_react_tools(AGENT_MODE_READONLY)

    assert "apply_patch" in full_tools

    assert "apply_patch" not in readonly_tools

    assert len(full_tools) == 15

    assert len(readonly_tools) == 10


def test_run_tool_apply_patch_blocked_in_readonly_mode():
    token = set_agent_mode(AGENT_MODE_READONLY)

    try:
        result = run_tool(
            "apply_patch",
            {"path": "sample.txt", "new_content": "updated\n"},
        )

        assert "readonly" in tool_result_message(result)

        assert "apply_patch" in tool_result_message(result)

    finally:
        reset_agent_mode(token)


def test_run_tool_apply_patch_requires_confirmation(monkeypatch):
    monkeypatch.setattr(
        "tools.tool_manager.request_tool_confirmation",
        lambda action, args, confirm_callback=None: False,
    )

    result = run_tool(
        "apply_patch",
        {"path": "sample.txt", "new_content": "updated\n"},
    )

    assert tool_result_message(result) == "用户已取消执行工具: apply_patch"


def test_run_tool_apply_patch_success_with_skip_confirm(isolated_git_repo):
    git_create_backup()

    confirm_token = set_skip_tool_confirm(True)

    try:
        result = run_tool(
            "apply_patch",
            {"path": "sample.txt", "new_content": "updated\n"},
        )

        assert "Patch 应用完成" in tool_result_message(result)

        assert (
            isolated_git_repo / "sample.txt"
        ).read_text(encoding="utf-8") == "updated\n"

    finally:
        reset_skip_tool_confirm(confirm_token)


def test_run_tool_apply_patch_writes_patch_apply_audit_event(isolated_git_repo):
    git_create_backup()

    confirm_token = set_skip_tool_confirm(True)

    audit_file = isolated_git_repo / "audit.jsonl"

    try:
        run_tool(
            "apply_patch",
            {"path": "sample.txt", "new_content": "updated\n"},
        )

        events = [
            json.loads(line)
            for line in audit_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        patch_events = [
            event for event in events if event.get("event") == "patch_apply"
        ]

        assert patch_events

        assert patch_events[-1]["path"] == "sample.txt"

        assert patch_events[-1]["status"] == "success"

    finally:
        reset_skip_tool_confirm(confirm_token)


def test_run_tool_apply_patch_rejects_without_backup(isolated_git_repo):
    confirm_token = set_skip_tool_confirm(True)

    try:
        result = run_tool(
            "apply_patch",
            {"path": "sample.txt", "new_content": "updated\n"},
        )

        assert "备份" in tool_result_message(result)

        assert (
            isolated_git_repo / "sample.txt"
        ).read_text(encoding="utf-8") == "original\n"

    finally:
        reset_skip_tool_confirm(confirm_token)


def test_tool_confirm_truncates_new_content_for_display():
    from security.tool_confirm import _format_confirm_args

    display = _format_confirm_args(
        "apply_patch",
        {"path": "sample.txt", "new_content": "x" * 300},
    )

    assert display["new_content"].endswith("...[truncated]")

    assert len(display["new_content"]) < 300


def test_existing_write_repo_file_still_requires_confirm_only():
    assert "write_repo_file" in CONFIRM_REQUIRED_TOOLS

    assert TOOLS["write_repo_file"]["function"].__name__ == "write_repo_file"
