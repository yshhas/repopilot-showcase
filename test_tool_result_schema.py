import json


import config.settings as settings
import tools.tool_manager as tool_manager_module
from audit.context import reset_agent_mode, set_agent_mode
from config.agent_mode import (
    AGENT_MODE_FULL,
    AGENT_MODE_READONLY,
    tool_blocked_message,
)
from context.mutation_fsm import (
    MutationWorkflowState,
    reset_mutation_fsm,
)
from tools.result_schema import (
    REJECT_CODE_CONFIRM_REJECTED,
    REJECT_CODE_MUTATION_FSM_BLOCKED,
    REJECT_CODE_TOOL_NOT_ALLOWED,
    REJECT_CODE_VALIDATION_ERROR,
    finalize_tool_result,
    format_tool_result_for_display,
    format_tool_result_for_memory,
    is_tool_reject,
    is_tool_result_error,
    tool_reject,
    tool_result_audit_fields,
    tool_result_message,
)
from tools.tool_manager import run_tool


PROPOSAL_TEXT = "修改方案\nsummary: test"
BACKUP_TEXT = "Git 备份完成\nbranch: agent-backup/test"


def _load_audit_events(path):
    if not path.exists():
        return []

    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def _patch_audit_db(tmp_path, monkeypatch):
    db_file = tmp_path / "tasks.db"
    audit_file = tmp_path / "audit.jsonl"
    monkeypatch.setattr(settings, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", audit_file)

    import audit.audit_log as audit_log_module

    monkeypatch.setattr(audit_log_module, "AUDIT_LOG_FILE", audit_file)
    return audit_file


def _enable_str(monkeypatch):
    monkeypatch.setattr(settings, "STRUCTURED_TOOL_REJECT_ENABLED", True)


def _disable_str(monkeypatch):
    monkeypatch.setattr(settings, "STRUCTURED_TOOL_REJECT_ENABLED", False)


def test_tool_reject_shape():
    reject = tool_reject(
        "validation_error",
        "参数错误: path - Field required",
        details={"tool": "read_repo_file", "field": "path"},
    )

    assert reject["ok"] is False
    assert reject["code"] == "validation_error"
    assert reject["message"].startswith("参数错误:")
    assert reject["details"]["field"] == "path"


def test_is_tool_reject_discriminates_success_string():
    assert not is_tool_reject("Patch 应用完成")
    assert is_tool_reject(
        tool_reject("confirm_rejected", "用户已取消执行工具: apply_patch")
    )


def test_finalize_tool_result_flag_off_returns_legacy_string(monkeypatch):
    _disable_str(monkeypatch)
    reject = tool_reject(
        REJECT_CODE_TOOL_NOT_ALLOWED,
        tool_blocked_message("apply_patch", AGENT_MODE_READONLY),
    )

    final = finalize_tool_result(reject)

    assert isinstance(final, str)
    assert final == tool_blocked_message("apply_patch", AGENT_MODE_READONLY)
    assert not is_tool_reject(final)


def test_finalize_tool_result_flag_on_keeps_dict(monkeypatch):
    _enable_str(monkeypatch)
    reject = tool_reject("confirm_rejected", "用户已取消执行工具: apply_patch")

    final = finalize_tool_result(reject)

    assert is_tool_reject(final)
    assert final["code"] == "confirm_rejected"


def test_format_tool_result_for_memory_is_message_only():
    reject = tool_reject(
        REJECT_CODE_MUTATION_FSM_BLOCKED,
        "Mutation workflow blocked: tool=apply_patch code=mutation_fsm_blocked",
        details={"tool": "apply_patch"},
    )

    memory_text = format_tool_result_for_memory(reject)

    assert memory_text == reject["message"]
    assert "<!-- tool_reject" not in memory_text


def test_tool_result_audit_fields_flag_on(monkeypatch):
    _enable_str(monkeypatch)
    reject = tool_reject(
        REJECT_CODE_VALIDATION_ERROR,
        "参数错误: path - Field required",
        details={"tool": "read_repo_file", "field": "path"},
    )

    text, code, details = tool_result_audit_fields(reject)

    assert text == reject["message"]
    assert code == REJECT_CODE_VALIDATION_ERROR
    assert details["field"] == "path"


def test_tool_result_audit_fields_flag_off_omits_structured_fields(monkeypatch):
    _disable_str(monkeypatch)
    reject = tool_reject(
        REJECT_CODE_VALIDATION_ERROR,
        "参数错误: path - Field required",
        details={"tool": "read_repo_file", "field": "path"},
    )

    text, code, details = tool_result_audit_fields(reject)

    assert text == reject["message"]
    assert code is None
    assert details is None


def test_is_tool_result_error_covers_legacy_and_structured_rejects():
    reject = tool_reject(REJECT_CODE_CONFIRM_REJECTED, "用户已取消执行工具: apply_patch")

    assert is_tool_result_error(reject)
    assert is_tool_result_error("参数错误: path - Field required")
    assert is_tool_result_error("不存在的工具")
    assert is_tool_result_error(
        "Mutation workflow blocked: tool=apply_patch current=ANALYZING required=BACKED_UP"
    )
    assert is_tool_result_error(tool_blocked_message("apply_patch", AGENT_MODE_READONLY))
    assert not is_tool_result_error("Patch 应用完成")
    assert not is_tool_result_error("跳过重复 apply_patch: sample.txt")


def test_run_tool_readonly_block_flag_off_legacy_string(tmp_path, monkeypatch):
    audit_file = _patch_audit_db(tmp_path, monkeypatch)
    _disable_str(monkeypatch)
    mode_token = set_agent_mode(AGENT_MODE_READONLY)

    result = run_tool("apply_patch", {"path": "sample.txt", "new_content": "x\n"})

    reset_agent_mode(mode_token)

    assert result == tool_blocked_message("apply_patch", AGENT_MODE_READONLY)
    events = _load_audit_events(audit_file)
    tool_calls = [event for event in events if event.get("event") == "tool_call"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["status"] == "error"
    assert "reject_code" not in tool_calls[0]


def test_run_tool_readonly_block_flag_on_structured(tmp_path, monkeypatch):
    audit_file = _patch_audit_db(tmp_path, monkeypatch)
    _enable_str(monkeypatch)
    mode_token = set_agent_mode(AGENT_MODE_READONLY)

    result = run_tool("apply_patch", {"path": "sample.txt", "new_content": "x\n"})

    reset_agent_mode(mode_token)

    assert is_tool_reject(result)
    assert result["code"] == REJECT_CODE_TOOL_NOT_ALLOWED
    assert result["message"] == tool_blocked_message("apply_patch", AGENT_MODE_READONLY)

    events = _load_audit_events(audit_file)
    tool_calls = [event for event in events if event.get("event") == "tool_call"]
    assert tool_calls[0]["reject_code"] == REJECT_CODE_TOOL_NOT_ALLOWED
    assert tool_calls[0]["reject_details"]["agent_mode"] == AGENT_MODE_READONLY


def test_run_tool_validation_error_flag_on(tmp_path, monkeypatch):
    audit_file = _patch_audit_db(tmp_path, monkeypatch)
    _enable_str(monkeypatch)
    mode_token = set_agent_mode(AGENT_MODE_FULL)

    result = run_tool("read_repo_file", {})

    reset_agent_mode(mode_token)

    assert is_tool_reject(result)
    assert result["code"] == REJECT_CODE_VALIDATION_ERROR
    assert result["message"].startswith("参数错误:")

    events = _load_audit_events(audit_file)
    tool_calls = [event for event in events if event.get("event") == "tool_call"]
    assert tool_calls[0]["status"] == "error"
    assert tool_calls[0]["reject_code"] == REJECT_CODE_VALIDATION_ERROR


def test_run_tool_confirm_reject_flag_on(tmp_path, monkeypatch):
    _patch_audit_db(tmp_path, monkeypatch)
    _enable_str(monkeypatch)
    # Isolate confirm-gate from default-on FSM (confirm runs after FSM check).
    monkeypatch.setattr(settings, "MUTATION_FSM_ENABLED", False)
    mode_token = set_agent_mode(AGENT_MODE_FULL)
    monkeypatch.setattr(tool_manager_module, "is_tool_confirm_skipped", lambda: False)
    monkeypatch.setattr(
        tool_manager_module,
        "request_tool_confirmation",
        lambda *args, **kwargs: False,
    )

    result = run_tool("apply_patch", {"path": "sample.txt", "new_content": "x\n"})

    reset_agent_mode(mode_token)

    assert is_tool_reject(result)
    assert result["code"] == REJECT_CODE_CONFIRM_REJECTED
    assert result["message"] == "用户已取消执行工具: apply_patch"


def test_run_tool_fsm_block_flag_on_structured_and_audit(tmp_path, monkeypatch):
    audit_file = _patch_audit_db(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "MUTATION_FSM_ENABLED", True)
    _enable_str(monkeypatch)
    reset_mutation_fsm()
    mode_token = set_agent_mode(AGENT_MODE_FULL)

    result = run_tool("apply_patch", {"path": "sample.txt", "new_content": "x\n"})

    reset_agent_mode(mode_token)

    assert is_tool_reject(result)
    assert result["code"] == REJECT_CODE_MUTATION_FSM_BLOCKED
    assert format_tool_result_for_display(result).startswith("Mutation workflow blocked:")

    events = _load_audit_events(audit_file)
    tool_calls = [event for event in events if event.get("event") == "tool_call"]
    blocked = [event for event in events if event.get("event") == "mutation_fsm_blocked"]

    assert tool_calls[0]["reject_code"] == REJECT_CODE_MUTATION_FSM_BLOCKED
    assert tool_calls[0]["reject_details"]["current_state"] == MutationWorkflowState.ANALYZING.value
    assert len(blocked) == 1
    assert blocked[0]["code"] == REJECT_CODE_MUTATION_FSM_BLOCKED


def test_run_tool_fsm_block_flag_off_legacy_string(tmp_path, monkeypatch):
    audit_file = _patch_audit_db(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "MUTATION_FSM_ENABLED", True)
    _disable_str(monkeypatch)
    reset_mutation_fsm()
    mode_token = set_agent_mode(AGENT_MODE_FULL)

    result = run_tool("apply_patch", {"path": "sample.txt", "new_content": "x\n"})

    reset_agent_mode(mode_token)

    assert isinstance(result, str)
    assert result.startswith("Mutation workflow blocked:")
    assert "code=mutation_fsm_blocked" in result

    events = _load_audit_events(audit_file)
    tool_calls = [event for event in events if event.get("event") == "tool_call"]
    assert tool_calls[0]["status"] == "error"
    assert "reject_code" not in tool_calls[0]
    assert any(event.get("event") == "mutation_fsm_blocked" for event in events)


def test_run_tool_unknown_tool_flag_on(tmp_path, monkeypatch):
    _patch_audit_db(tmp_path, monkeypatch)
    _enable_str(monkeypatch)
    mode_token = set_agent_mode(AGENT_MODE_FULL)

    result = run_tool("missing_tool", {})

    reset_agent_mode(mode_token)

    assert is_tool_reject(result)
    assert result["code"] == "tool_not_found"
    assert tool_result_message(result) == "不存在的工具"
