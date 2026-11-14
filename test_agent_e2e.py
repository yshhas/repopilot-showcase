"""Agent end-to-end tests: full react_agent() flows with real tool execution.

These tests verify that the complete agent pipeline — LLM parsing → tool
execution → state management → result verification — works correctly in
an isolated git repository.
"""

import json
import os

import pytest

from audit.context import (
    reset_skip_tool_confirm,
    set_skip_tool_confirm,
)
from config.agent_mode import AGENT_MODE_FULL, AGENT_MODE_READONLY
from react_agent import react_agent


# ── Helpers ────────────────────────────────────────────────────────────────


def _read_file(repo_root: str, filename: str) -> str:
    p = os.path.join(repo_root, filename)
    return open(p, encoding="utf-8").read()


def _install_llm_sequence(monkeypatch, responses: list[str]):
    """Replace react_agent.ask_ai with a sequence of pre-determined responses."""
    state = {"idx": 0}

    def fake_ask_ai(memory, agent_mode=None):
        if state["idx"] >= len(responses):
            raise AssertionError(
                f"ask_ai called {state['idx'] + 1} times but only "
                f"{len(responses)} responses provided"
            )
        resp = responses[state["idx"]]
        state["idx"] += 1
        return resp

    monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)
    return state


# ── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("disable_mutation_fsm")
class TestAgentE2EReadonly:
    """Read-only agent: read a file and finish."""

    def test_read_file_and_finish(self, isolated_git_repo, monkeypatch):
        _install_llm_sequence(monkeypatch, [
            json.dumps({"action": "read_repo_file", "args": {"path": "sample.txt"}}),
            json.dumps({"action": "finish", "answer": "文件内容为 original"}),
        ])

        answer, memory = react_agent(
            "读取 sample.txt 的内容",
            max_steps=5,
            agent_mode=AGENT_MODE_READONLY,
        )

        assert answer == "文件内容为 original"
        assert len(memory) >= 3  # user question + assistant + tool result


@pytest.mark.usefixtures("disable_mutation_fsm")
class TestAgentE2EMultiTool:
    """Agent executes multiple tools in sequence before finishing."""

    def test_read_and_search_in_repo(self, isolated_git_repo, monkeypatch):
        _install_llm_sequence(monkeypatch, [
            json.dumps({"action": "list_repo_files", "args": {"path": "."}}),
            json.dumps({"action": "read_repo_file", "args": {"path": "sample.txt"}}),
            json.dumps({"action": "git_status", "args": {}}),
            json.dumps({"action": "finish", "answer": "仓库检查完毕"}),
        ])

        answer, memory = react_agent(
            "检查仓库状态和文件内容",
            max_steps=10,
            agent_mode=AGENT_MODE_FULL,
        )

        assert answer == "仓库检查完毕"
        assert len(memory) >= 4  # user + multiple assistant/tool rounds


@pytest.mark.usefixtures("disable_mutation_fsm")
class TestAgentE2EWriteFlow:
    """Full mutation flow via write_repo_file path."""

    def test_write_flow_creates_file(self, isolated_git_repo, isolated_task_db, monkeypatch):
        repo_root = isolated_git_repo

        skip_token = set_skip_tool_confirm(True)
        try:
            _install_llm_sequence(monkeypatch, [
                # Step 1: backup
                json.dumps({"action": "git_create_backup", "args": {"message": "agent backup before write"}}),
                # Step 2: write new file
                json.dumps({
                    "action": "write_repo_file",
                    "args": {"path": "notes.md", "content": "# Project Notes\n\nHello world.\n"},
                }),
                # Step 3: done
                json.dumps({"action": "finish", "answer": "已创建 notes.md"}),
            ])

            answer, memory = react_agent(
                "创建 notes.md 文件",
                max_steps=10,
                agent_mode=AGENT_MODE_FULL,
            )

            assert answer == "已创建 notes.md"

            # Verify file was actually written
            content = _read_file(repo_root, "notes.md")
            assert content == "# Project Notes\n\nHello world.\n"

            # Verify original file untouched
            sample = _read_file(repo_root, "sample.txt")
            assert sample == "original\n"
        finally:
            reset_skip_tool_confirm(skip_token)


@pytest.mark.usefixtures("disable_mutation_fsm")
class TestAgentE2EObservability:
    """Verify observability metrics populate during agent runs."""

    def test_metrics_populated_after_agent_run(self, isolated_git_repo, monkeypatch):
        from observability import snapshot

        # Record baseline
        before = snapshot()

        _install_llm_sequence(monkeypatch, [
            json.dumps({"action": "read_repo_file", "args": {"path": "sample.txt"}}),
            json.dumps({"action": "git_status", "args": {}}),
            json.dumps({"action": "finish", "answer": "检查完成"}),
        ])

        react_agent("检查仓库状态", max_steps=5, agent_mode=AGENT_MODE_FULL)

        after = snapshot()

        # After running real tools through the agent loop:
        # - at least 3 steps (read → git_status → finish)
        # - at least 3 LLM calls
        # - at least 2 tool calls (read_repo_file, git_status)
        assert after["agent"]["step_count"] > before["agent"]["step_count"], \
            "agent step_count should increase after agent run"
        assert after["llm"]["call_count"] > before["llm"]["call_count"], \
            "llm call_count should increase"
        assert after["tools"]["call_count"] > before["tools"]["call_count"], \
            "tool call_count should increase"

        # Tool-level detail
        tools_by_name = after["tools"]["by_name"]
        assert tools_by_name.get("read_repo_file", 0) >= 1
        assert tools_by_name.get("git_status", 0) >= 1


@pytest.mark.usefixtures("disable_mutation_fsm")
class TestAgentE2EPlainResponse:
    """Agent returns plain text (non-JSON) when no tool call is needed."""

    def test_plain_text_answer_no_tools(self, isolated_git_repo, monkeypatch):
        _install_llm_sequence(monkeypatch, [
            "这个问题不需要工具，直接回答即可。",
        ])

        answer, memory = react_agent(
            "什么是 Python？",
            max_steps=5,
            agent_mode=AGENT_MODE_READONLY,
        )

        assert answer == "这个问题不需要工具，直接回答即可。"
        assert len(memory) >= 1  # user message; plain-text path exits before appending assistant
