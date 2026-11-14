import pytest

from audit.context import reset_agent_mode, set_agent_mode
from config.agent_mode import AGENT_MODE_FULL, AGENT_MODE_READONLY
from config.settings import CONFIRM_REQUIRED_TOOLS
from tools.result_schema import tool_result_message
from tools.tool_manager import TOOLS, build_tools_prompt_section, get_react_tools, run_tool


@pytest.fixture(autouse=True)
def _disable_fsm_for_diff_tool_unit_tests(disable_mutation_fsm):
    return disable_mutation_fsm


def _setup_repo(tmp_path, monkeypatch, *, content="original\n"):
    monkeypatch.setenv("REPO_ROOT", str(tmp_path))

    import config.settings as settings

    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)

    import context.project_context as project_context_module

    monkeypatch.setattr(project_context_module, "REPO_ROOT", tmp_path)

    import security.path_guard as path_guard

    monkeypatch.setattr(path_guard, "REPO_ROOT", tmp_path)

    sample = tmp_path / "sample.txt"

    sample.write_text(content, encoding="utf-8")


def test_generate_unified_diff_registered_as_react_tool():
    tool = TOOLS["generate_unified_diff"]

    assert tool["react"] is True

    assert tool["args_model"].__name__ == "GenerateUnifiedDiffArgs"


def test_generate_unified_diff_in_full_and_readonly_react_sets():
    full_tools = get_react_tools(AGENT_MODE_FULL)

    readonly_tools = get_react_tools(AGENT_MODE_READONLY)

    assert "generate_unified_diff" in full_tools

    assert "generate_unified_diff" in readonly_tools

    assert "apply_patch" in full_tools

    assert "apply_patch" not in readonly_tools

    assert len(full_tools) == 15

    assert len(readonly_tools) == 10


def test_generate_unified_diff_not_in_confirm_required_tools():
    assert "generate_unified_diff" not in CONFIRM_REQUIRED_TOOLS


def test_run_tool_generate_unified_diff_returns_preview(tmp_path, monkeypatch):
    _setup_repo(tmp_path, monkeypatch)

    result = run_tool(
        "generate_unified_diff",
        {"path": "sample.txt", "new_content": "updated\n"},
    )

    assert "Unified diff 预览" in tool_result_message(result)

    assert "-original" in tool_result_message(result)

    assert "+updated" in tool_result_message(result)


def test_run_tool_generate_unified_diff_readonly_mode(tmp_path, monkeypatch):
    _setup_repo(tmp_path, monkeypatch)

    token = set_agent_mode(AGENT_MODE_READONLY)

    try:
        result = run_tool(
            "generate_unified_diff",
            {"path": "sample.txt", "new_content": "updated\n"},
        )

        assert "Unified diff 预览" in tool_result_message(result)

    finally:
        reset_agent_mode(token)


def test_run_tool_generate_unified_diff_does_not_modify_file(tmp_path, monkeypatch):
    _setup_repo(tmp_path, monkeypatch)

    run_tool(
        "generate_unified_diff",
        {"path": "sample.txt", "new_content": "updated\n"},
    )

    assert (tmp_path / "sample.txt").read_text(encoding="utf-8") == "original\n"


def test_run_tool_generate_unified_diff_validates_args():
    result = run_tool(
        "generate_unified_diff",
        {"path": "sample.txt"},
    )

    assert "参数错误" in tool_result_message(result)


def test_build_tools_prompt_includes_generate_unified_diff():
    prompt = build_tools_prompt_section(AGENT_MODE_FULL)

    assert "generate_unified_diff" in prompt

    readonly_prompt = build_tools_prompt_section(AGENT_MODE_READONLY)

    assert "generate_unified_diff" in readonly_prompt

    assert "write_repo_file" not in readonly_prompt


def test_existing_write_repo_file_tool_unchanged():
    tool = TOOLS["write_repo_file"]

    assert tool["function"].__name__ == "write_repo_file"

    assert tool["args_model"].__name__ == "WriteRepoFileArgs"
