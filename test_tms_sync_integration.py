"""Integration tests for react_agent TMS sync hooks (PR-M1)."""

import pytest

import config.settings as settings
from context.tms import MutationWorkflowState, get_mutation_state, reset_mutation_state
from react_agent import react_agent


def _patch_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)


@pytest.fixture(autouse=True)
def _enable_tms_adapter(monkeypatch, tmp_path):
    _patch_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "TMS_ADAPTER_ENABLED", True)
    monkeypatch.setattr(settings, "PARITY_STRICT", False)
    reset_mutation_state()
    yield


def test_react_agent_post_tool_syncs_shadow(monkeypatch):
    calls = []

    def fake_ask_ai(memory, agent_mode=None):
        if not calls:
            calls.append(1)
            return '{"action": "git_status", "args": {}}'
        return "done"

    monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)
    monkeypatch.setattr(
        "tools.tool_manager.run_tool",
        lambda name, args: "Git 状态正常",
    )

    answer, _memory = react_agent(
        "check git",
        task_id="sync01",
        max_steps=5,
    )

    assert answer
    shadow = get_mutation_state()
    assert shadow.workflow.state == MutationWorkflowState.ANALYZING


def test_react_agent_fresh_task_resets_shadow(monkeypatch):
    def fake_ask_ai(memory, agent_mode=None):
        return "analysis complete"

    monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)

    react_agent("hello", task_id="fresh01", max_steps=3)
    shadow = get_mutation_state()
    assert shadow.artifacts.backup is None
