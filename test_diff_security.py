import inspect
import subprocess

import pytest

import config.settings as settings
from audit.context import reset_agent_mode, set_agent_mode
from config.agent_mode import (
    AGENT_MODE_FULL,
    AGENT_MODE_READONLY,
    MUTATION_TOOLS,
    get_tool_order_for_mode,
    is_tool_allowed,
    tool_blocked_message,
)
from config.settings import CONFIRM_REQUIRED_TOOLS
from tools.diff_engine import preview_unified_diff
from tools.result_schema import tool_result_message
from tools.tool_manager import get_react_tools, run_tool


@pytest.fixture(autouse=True)
def _disable_fsm_for_diff_security_unit_tests(disable_mutation_fsm):
    return disable_mutation_fsm


def test_apply_patch_classified_as_mutation_tool():
    assert "apply_patch" in MUTATION_TOOLS


def test_generate_unified_diff_not_classified_as_mutation():
    assert "generate_unified_diff" not in MUTATION_TOOLS


def test_readonly_allows_generate_unified_diff_permission():
    assert is_tool_allowed(AGENT_MODE_READONLY, "generate_unified_diff") is True


def test_readonly_blocks_apply_patch_permission():
    assert is_tool_allowed(AGENT_MODE_READONLY, "apply_patch") is False


def test_full_mode_allows_diff_tools():
    assert is_tool_allowed(AGENT_MODE_FULL, "generate_unified_diff") is True

    assert is_tool_allowed(AGENT_MODE_FULL, "apply_patch") is True


def test_readonly_tool_order_includes_generate_unified_diff():
    readonly_order = get_tool_order_for_mode(AGENT_MODE_READONLY)

    assert "generate_unified_diff" in readonly_order

    assert "apply_patch" not in readonly_order


def test_react_tool_count_after_diff_tool_registration():
    assert len(get_react_tools(AGENT_MODE_FULL)) == 15

    assert len(get_react_tools(AGENT_MODE_READONLY)) == 10

    assert "generate_unified_diff" in get_react_tools(AGENT_MODE_FULL)

    assert "generate_unified_diff" in get_react_tools(AGENT_MODE_READONLY)

    assert "apply_patch" in get_react_tools(AGENT_MODE_FULL)

    assert "apply_patch" not in get_react_tools(AGENT_MODE_READONLY)


def test_generate_unified_diff_not_in_confirm_required_tools():
    assert "generate_unified_diff" not in CONFIRM_REQUIRED_TOOLS


def test_run_tool_blocks_apply_patch_in_readonly_mode():
    token = set_agent_mode(AGENT_MODE_READONLY)

    try:
        result = run_tool(
            "apply_patch",
            {"path": "sample.txt", "new_content": "x\n"},
        )

        assert tool_result_message(result) == tool_blocked_message(
            "apply_patch",
            AGENT_MODE_READONLY,
        )

    finally:
        reset_agent_mode(token)


def test_run_tool_allows_generate_unified_diff_in_readonly_mode(tmp_path, monkeypatch):
    _setup_repo(tmp_path, monkeypatch)

    token = set_agent_mode(AGENT_MODE_READONLY)

    try:
        result = run_tool(
            "generate_unified_diff",
            {"path": "sample.txt", "new_content": "x\n"},
        )

        assert "Unified diff 预览" in tool_result_message(result)

    finally:
        reset_agent_mode(token)


def _setup_repo(tmp_path, monkeypatch, *, content="original\n"):
    monkeypatch.setenv("REPO_ROOT", str(tmp_path))

    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)

    import context.project_context as project_context_module

    monkeypatch.setattr(project_context_module, "REPO_ROOT", tmp_path)

    import security.path_guard as path_guard

    monkeypatch.setattr(path_guard, "REPO_ROOT", tmp_path)

    sample = tmp_path / "sample.txt"

    sample.write_text(content, encoding="utf-8")


def test_preview_unified_diff_does_not_modify_file(tmp_path, monkeypatch):
    _setup_repo(tmp_path, monkeypatch)

    result = preview_unified_diff("sample.txt", "updated\n")

    assert "Unified diff 预览" in tool_result_message(result)

    assert "-original" in tool_result_message(result)

    assert "+updated" in tool_result_message(result)

    assert (tmp_path / "sample.txt").read_text(encoding="utf-8") == "original\n"


def test_preview_unified_diff_blocks_sensitive_path(tmp_path, monkeypatch):
    _setup_repo(tmp_path, monkeypatch)

    env_file = tmp_path / ".env"

    env_file.write_text("SECRET=1\n", encoding="utf-8")

    result = preview_unified_diff(".env", "SECRET=2\n")

    assert "敏感" in tool_result_message(result)


def test_preview_unified_diff_blocks_path_traversal(tmp_path, monkeypatch):
    _setup_repo(tmp_path, monkeypatch)

    result = preview_unified_diff("../outside.txt", "bad\n")

    assert "越界" in tool_result_message(result)


def test_apply_repo_patch_subprocess_does_not_use_shell():
    import tools.patch_apply as patch_apply_module

    run_git_source = inspect.getsource(patch_apply_module._run_git)

    assert "shell=True" not in run_git_source


def test_run_git_uses_repo_root_cwd(tmp_path, monkeypatch):
    import tools.patch_apply as patch_apply_module

    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    observed: list[str] = []

    original_run = subprocess.run

    def tracking_run(cmd, **kwargs):
        observed.append(str(kwargs.get("cwd")))

        return original_run(cmd, **kwargs)

    monkeypatch.setattr(patch_apply_module.subprocess, "run", tracking_run)

    patch_apply_module._run_git(["rev-parse", "--is-inside-work-tree"])

    assert observed

    assert observed[0] == str(tmp_path)
