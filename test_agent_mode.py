import pytest

from config.agent_mode import (
    AGENT_MODE_FULL,
    AGENT_MODE_READONLY,
    MUTATION_TOOLS,
    parse_agent_mode,
    resolve_agent_mode,
    tool_blocked_message,
)
from audit.context import get_agent_mode, reset_agent_mode, set_agent_mode
from llm import build_system_prompt
from tools.result_schema import tool_result_message
from tools.tool_manager import get_react_tools, run_tool


def test_parse_agent_mode_defaults_to_full():

    assert parse_agent_mode(None) == AGENT_MODE_FULL

    assert parse_agent_mode("full") == AGENT_MODE_FULL

    assert parse_agent_mode("READONLY") == AGENT_MODE_READONLY


def test_parse_agent_mode_rejects_invalid():

    with pytest.raises(ValueError):

        parse_agent_mode("invalid")


def test_resolve_agent_mode_request_over_env(monkeypatch):

    monkeypatch.setattr("config.settings.AGENT_MODE", "full")

    assert resolve_agent_mode("readonly") == AGENT_MODE_READONLY

    assert resolve_agent_mode(None) == AGENT_MODE_FULL


def test_readonly_tool_filter_excludes_mutations():

    tools = get_react_tools(AGENT_MODE_READONLY)

    for name in MUTATION_TOOLS:

        assert name not in tools

    assert "propose_code_changes" in tools

    assert "read_repo_file" in tools


def test_full_mode_includes_all_react_tools():

    readonly_names = set(get_react_tools(AGENT_MODE_READONLY))

    full_names = set(get_react_tools(AGENT_MODE_FULL))

    from tools.tool_manager import TOOLS

    for name in MUTATION_TOOLS:

        tool = TOOLS.get(name)

        if tool and tool.get("react"):

            assert name in full_names

    assert readonly_names < full_names


def test_run_tool_blocks_mutation_in_readonly_mode():

    token = set_agent_mode(AGENT_MODE_READONLY)


    try:

        result = run_tool(
            "write_repo_file",
            {"path": "test.txt", "content": "x"},
        )

        assert "readonly" in tool_result_message(result)

        assert "write_repo_file" in tool_result_message(result)

    finally:

        reset_agent_mode(token)


def test_run_tool_allows_propose_in_readonly_mode(monkeypatch):

    import tools.tool_manager as tm

    token = set_agent_mode(AGENT_MODE_READONLY)

    monkeypatch.setitem(
        tm.TOOLS["propose_code_changes"],
        "function",
        lambda task, target_files="", max_chars=20000, affected_files="": "proposal ok",
    )


    try:

        result = run_tool(
            "propose_code_changes",
            {"task": "analyze readme"},
        )

        assert tool_result_message(result) == "proposal ok"

    finally:

        reset_agent_mode(token)


def test_readonly_prompt_describes_readonly_mode():

    prompt = build_system_prompt(AGENT_MODE_READONLY)

    assert "propose_code_changes" in prompt

    assert "只读模式" in prompt

    assert "git_create_backup" not in get_react_tools(AGENT_MODE_READONLY)


def test_full_prompt_includes_change_workflow():

    prompt = build_system_prompt(AGENT_MODE_FULL)

    assert "git_create_backup" in prompt

    assert "write_repo_file" in prompt

    assert "generate_unified_diff" in prompt

    assert "apply_patch" in prompt


def test_context_agent_mode_used_by_run_tool(monkeypatch):

    monkeypatch.setattr("config.settings.AGENT_MODE", "full")

    token = set_agent_mode(AGENT_MODE_READONLY)


    try:

        assert get_agent_mode() == AGENT_MODE_READONLY

        result = run_tool("git_rollback", {})

        assert tool_result_message(result) == tool_blocked_message(
            "git_rollback",
            AGENT_MODE_READONLY,
        )

    finally:

        reset_agent_mode(token)
