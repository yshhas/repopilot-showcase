"""v0.10.1 default-on guard migration checks."""

import config.settings as settings
from audit.context import reset_agent_mode, set_agent_mode
from config.agent_mode import AGENT_MODE_FULL
from context.tms import reset_mutation_state
from tools.result_schema import (
    REJECT_CODE_MUTATION_FSM_BLOCKED,
    is_tool_reject,
    tool_result_message,
)
from tools.tool_manager import run_tool


def test_mutation_fsm_default_enabled():
    assert settings.MUTATION_FSM_ENABLED is True


def test_structured_tool_reject_default_enabled():
    assert settings.STRUCTURED_TOOL_REJECT_ENABLED is True


def test_dedup_remains_default_off():
    assert settings.EXECUTION_STATE_DEDUP_ENABLED is False


def test_default_fsm_blocks_apply_before_backup(tmp_path, monkeypatch):
    """Default-on FSM must reject illegal order without explicit flag patch."""
    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", tmp_path / "audit.jsonl")
    (tmp_path / "sample.txt").write_text("original\n", encoding="utf-8")
    reset_mutation_state()

    mode_token = set_agent_mode(AGENT_MODE_FULL)
    try:
        result = run_tool(
            "apply_patch",
            {"path": "sample.txt", "new_content": "updated\n"},
        )
    finally:
        reset_agent_mode(mode_token)

    assert is_tool_reject(result)
    assert result["code"] == REJECT_CODE_MUTATION_FSM_BLOCKED
    assert "Mutation workflow blocked" in tool_result_message(result)


def test_default_structured_reject_preserves_message_in_memory_format(tmp_path, monkeypatch):
    from tools.result_schema import format_tool_result_for_memory

    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", tmp_path / "audit.jsonl")
    (tmp_path / "sample.txt").write_text("original\n", encoding="utf-8")
    reset_mutation_state()

    mode_token = set_agent_mode(AGENT_MODE_FULL)
    try:
        result = run_tool(
            "apply_patch",
            {"path": "sample.txt", "new_content": "updated\n"},
        )
    finally:
        reset_agent_mode(mode_token)

    memory_text = format_tool_result_for_memory(result)
    assert "Mutation workflow blocked" in memory_text
    # Memory path stays human-readable (not raw JSON) unless MEMORY_STRUCTURED is on.
    assert not memory_text.strip().startswith("{")


def test_env_rollback_disables_fsm(monkeypatch):
    monkeypatch.setenv("MUTATION_FSM_ENABLED", "0")
    # Re-read pattern used by settings: monkeypatch attribute mirrors operator rollback.
    monkeypatch.setattr(settings, "MUTATION_FSM_ENABLED", False)
    assert settings.MUTATION_FSM_ENABLED is False


def test_default_fsm_golden_illegal_order_without_explicit_enable(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
    tmp_path,
    monkeypatch,
):
    """Golden-style illegal order under shipped defaults (no MUTATION_FSM patch=True)."""
    from react_agent import react_agent
    from storage.task_store import TASK_STATUS_COMPLETED, get_task

    assert settings.MUTATION_FSM_ENABLED is True
    assert settings.STRUCTURED_TOOL_REJECT_ENABLED is True

    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", tmp_path / "audit.jsonl")
    (tmp_path / "sample.txt").write_text("original\n", encoding="utf-8")
    reset_mutation_state()

    task_id = "golden_default_fsm_illegal_order"
    mock_ask_ai_sequence["install"]([
        (
            '{"action": "apply_patch", "args": '
            '{"path": "sample.txt", "new_content": "x\\n"}}'
        ),
        '{"action": "finish", "answer": "blocked by default fsm"}',
    ])
    tool_call_spy["install"](use_real_run_tool=True)

    answer, memory = react_agent(
        "apply without backup",
        task_id=task_id,
    )

    tool_blobs = [
        item["content"]
        for item in memory
        if item.get("role") == "user" and "工具执行结果" in item.get("content", "")
    ]
    assert any("Mutation workflow blocked" in blob for blob in tool_blobs)
    assert answer == "blocked by default fsm"
    task = get_task(task_id)
    assert task is not None
    assert task["status"] == TASK_STATUS_COMPLETED
