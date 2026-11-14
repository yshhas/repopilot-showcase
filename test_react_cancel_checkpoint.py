import config.settings as settings
import storage.checkpoint_store as checkpoint_store_module
import storage.task_store as task_store_module
from storage.checkpoint_store import count_checkpoints, get_latest_checkpoint
from storage.task_store import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    create_task,
    get_task,
    mark_task_cancelled,
    request_cancel,
)
from react_agent import react_agent


def _patch_agent_dbs(tmp_path, monkeypatch):
    db_file = tmp_path / "tasks.db"
    monkeypatch.setattr(settings, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(task_store_module, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(checkpoint_store_module, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(settings, "CHECKPOINT_ENABLED", True)
    return db_file


def test_cancel_flag_stops_agent_at_next_iteration(tmp_path, monkeypatch):
    _patch_agent_dbs(tmp_path, monkeypatch)
    task_id = "react-cancel-1"
    create_task(task_id, "cancel test", repo_root=str(tmp_path))

    ask_calls = {"count": 0}

    def fake_ask_ai(memory, agent_mode=None):
        ask_calls["count"] += 1
        if ask_calls["count"] == 1:
            return '{"action": "git_status", "args": {}}'
        return '{"action": "apply_patch", "args": {"path": "a.txt", "new_content": "x"}}'

    tool_calls = []

    def fake_run_tool(action, args):
        tool_calls.append(action)
        request_cancel(task_id)
        return action + " ok"

    monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)
    monkeypatch.setattr("react_agent.run_tool", fake_run_tool)

    answer, _memory = react_agent("start", task_id=task_id)

    assert answer == "任务已取消"
    assert tool_calls == ["git_status"]
    assert "apply_patch" not in tool_calls

    task = get_task(task_id)
    assert task["status"] == TASK_STATUS_CANCELLED
    assert task["cancel_requested"] == 0


def test_cancel_does_not_use_failed_status(tmp_path, monkeypatch):
    _patch_agent_dbs(tmp_path, monkeypatch)
    task_id = "react-cancel-2"
    create_task(task_id, "no failed", repo_root=str(tmp_path))

    def fake_ask_ai(memory, agent_mode=None):
        return '{"action": "git_status", "args": {}}'

    def fake_run_tool(action, args):
        request_cancel(task_id)
        return "ok"

    monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)
    monkeypatch.setattr("react_agent.run_tool", fake_run_tool)

    react_agent("start", task_id=task_id)

    task = get_task(task_id)
    assert task["status"] == TASK_STATUS_CANCELLED
    assert task["status"] != TASK_STATUS_FAILED


def test_checkpoint_saved_after_tool_iteration(tmp_path, monkeypatch):
    _patch_agent_dbs(tmp_path, monkeypatch)
    task_id = "react-cp-1"
    create_task(task_id, "checkpoint", repo_root=str(tmp_path))

    def fake_run_tool(action, args):
        return "tool ok"

    sequence = [
        '{"action": "git_status", "args": {}}',
        '{"action": "finish", "answer": "done after tool"}',
    ]
    calls = {"index": 0}

    def sequenced_ask_ai(memory, agent_mode=None):
        idx = calls["index"]
        calls["index"] += 1
        return sequence[min(idx, len(sequence) - 1)]

    monkeypatch.setattr("react_agent.ask_ai", sequenced_ask_ai)
    monkeypatch.setattr("react_agent.run_tool", fake_run_tool)

    react_agent("start", task_id=task_id)

    assert count_checkpoints(task_id) == 1
    latest = get_latest_checkpoint(task_id)
    assert latest is not None
    assert latest.step == 1
    assert len(latest.memory) >= 3
    assert latest.memory[-1]["content"].startswith("工具执行结果:")


def test_max_steps_saves_checkpoint_before_failed(tmp_path, monkeypatch):
    _patch_agent_dbs(tmp_path, monkeypatch)
    task_id = "react-cp-2"
    create_task(task_id, "max steps", repo_root=str(tmp_path))

    def fake_ask_ai(memory, agent_mode=None):
        return '{"action": "git_status", "args": {}}'

    def fake_run_tool(action, args):
        return "tool ok"

    monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)
    monkeypatch.setattr("react_agent.run_tool", fake_run_tool)

    react_agent(
        "start",
        task_id=task_id,
        max_steps=2,
    )

    task = get_task(task_id)
    assert task["status"] == TASK_STATUS_FAILED

    latest = get_latest_checkpoint(task_id)
    assert latest is not None
    assert latest.step == 2


def test_checkpoint_save_failure_does_not_fail_agent(tmp_path, monkeypatch):
    _patch_agent_dbs(tmp_path, monkeypatch)
    task_id = "react-cp-3"
    create_task(task_id, "cp fail ok", repo_root=str(tmp_path))

    def exploding_save(*args, **kwargs):
        raise RuntimeError("checkpoint boom")

    monkeypatch.setattr("storage.checkpoint_store.save_checkpoint", exploding_save)

    def fake_ask_ai(memory, agent_mode=None):
        return '{"action": "finish", "answer": "still done"}'

    monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)

    answer, _memory = react_agent("start", task_id=task_id)

    assert answer == "still done"
    assert get_task(task_id)["status"] == "completed"


def test_resume_from_checkpoint_continues_from_saved_step(tmp_path, monkeypatch):
    _patch_agent_dbs(tmp_path, monkeypatch)
    task_id = "react-resume-1"
    create_task(task_id, "resume unit", repo_root=str(tmp_path))
    mark_task_cancelled(task_id)

    initial_memory = [
        {"role": "user", "content": "original question"},
        {"role": "assistant", "content": '{"action": "git_status", "args": {}}'},
        {"role": "user", "content": "工具执行结果:\nbranch main"},
    ]

    ask_calls = {"count": 0}

    def fake_ask_ai(memory, agent_mode=None):
        ask_calls["count"] += 1
        assert len(memory) == 3
        assert memory[0]["content"] == "original question"
        return '{"action": "finish", "answer": "resumed step ok"}'

    monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)

    answer, memory = react_agent(
        "",
        task_id=task_id,
        resume_from_step=1,
        initial_memory=initial_memory,
        initial_context_state={"chars_used": 42, "files_read": ["x.py"]},
    )

    assert answer == "resumed step ok"
    assert ask_calls["count"] == 1
    assert get_task(task_id)["status"] == TASK_STATUS_COMPLETED

    from context.budget_state import get_context_budget_state

    state = get_context_budget_state()
    assert state.chars_used == 42
    assert state.files_read == ["x.py"]


def test_checkpoint_persists_execution_state_when_dedup_enabled(tmp_path, monkeypatch):
    _patch_agent_dbs(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", True)
    monkeypatch.setattr(settings, "CHECKPOINT_MUTATION_STATE_V2_ENABLED", True)

    task_id = "react-exec-state-1"
    create_task(task_id, "proposal checkpoint", repo_root=str(tmp_path))

    proposal_text = "===== 修改方案 =====\n摘要: add logging"

    def fake_run_tool(action, args):
        if action == "propose_code_changes":
            from tools.outcome_schema import SUCCESS_CODE_PROPOSAL_GENERATED, tool_success
            from context.tms.types import MilestoneToken
            from context.execution_state import compute_proposal_digest

            digest = compute_proposal_digest(proposal_text)
            return tool_success(
                SUCCESS_CODE_PROPOSAL_GENERATED,
                proposal_text,
                milestone=MilestoneToken.PROPOSED,
                details={"proposal_digest": digest},
            )
        return "tool ok"

    sequence = [
        (
            '{"action": "propose_code_changes", "args": '
            '{"task": "add logging"}}'
        ),
        '{"action": "finish", "answer": "done"}',
    ]
    calls = {"index": 0}

    def sequenced_ask_ai(memory, agent_mode=None):
        idx = calls["index"]
        calls["index"] += 1
        return sequence[min(idx, len(sequence) - 1)]

    monkeypatch.setattr("react_agent.ask_ai", sequenced_ask_ai)
    monkeypatch.setattr("react_agent.run_tool", fake_run_tool)

    react_agent("start", task_id=task_id)

    latest = get_latest_checkpoint(task_id)
    assert latest is not None
    assert latest.mutation_state is not None
    workflow = latest.mutation_state.get("workflow") or {}
    assert workflow.get("proposal_digest")
    assert (latest.mutation_state.get("artifacts") or {}).get("patch_applied") is False


def test_resume_restores_execution_state_and_injects_hint(tmp_path, monkeypatch):
    _patch_agent_dbs(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", True)

    task_id = "react-exec-state-2"
    create_task(task_id, "resume exec", repo_root=str(tmp_path))
    mark_task_cancelled(task_id)

    initial_memory = [
        {"role": "user", "content": "modify sample"},
        {"role": "assistant", "content": '{"action": "git_create_backup", "args": {}}'},
        {"role": "user", "content": "工具执行结果:\nGit 备份完成"},
    ]
    initial_execution_state = {
        "proposal_digest": "digest1234567890ab",
        "backup_branch": "agent-backup/20260720-120000",
        "backup_commit": "deadbeef",
        "diff_previewed_paths": ["sample.txt"],
        "patch_applied": False,
        "patch_applied_paths": [],
    }

    seen = {}

    def fake_ask_ai(memory, agent_mode=None):
        seen["memory"] = list(memory)
        return '{"action": "finish", "answer": "resumed with hint"}'

    monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)

    answer, _memory = react_agent(
        "",
        task_id=task_id,
        resume_from_step=1,
        initial_memory=initial_memory,
        initial_execution_state=initial_execution_state,
    )

    assert answer == "resumed with hint"
    assert any(
        item.get("content", "").startswith("[checkpoint]")
        for item in seen["memory"]
        if item.get("role") == "user"
    )

    from context.tms.context import get_shadow

    shadow = get_shadow()
    assert shadow.workflow.proposal_digest == "digest1234567890ab"
    assert shadow.artifacts.backup is not None
    assert shadow.artifacts.backup.backup_branch == "agent-backup/20260720-120000"
    assert shadow.artifacts.patch_applied is False


def test_execution_state_update_failure_does_not_fail_agent(tmp_path, monkeypatch):
    _patch_agent_dbs(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", True)

    task_id = "react-exec-state-3"
    create_task(task_id, "update fail ok", repo_root=str(tmp_path))

    def exploding_update(*args, **kwargs):
        raise RuntimeError("execution state boom")

    monkeypatch.setattr(
        "context.execution_state.update_from_tool_result",
        exploding_update,
    )

    def fake_run_tool(action, args):
        return "tool ok"

    sequence = [
        '{"action": "git_status", "args": {}}',
        '{"action": "finish", "answer": "still completed"}',
    ]
    calls = {"index": 0}

    def sequenced_ask_ai(memory, agent_mode=None):
        idx = calls["index"]
        calls["index"] += 1
        return sequence[min(idx, len(sequence) - 1)]

    monkeypatch.setattr("react_agent.ask_ai", sequenced_ask_ai)
    monkeypatch.setattr("react_agent.run_tool", fake_run_tool)

    answer, _memory = react_agent("start", task_id=task_id)

    assert answer == "still completed"
    assert get_task(task_id)["status"] == TASK_STATUS_COMPLETED


def test_flag_disabled_checkpoint_writes_v2_only(tmp_path, monkeypatch):
    _patch_agent_dbs(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", False)

    task_id = "react-exec-state-4"
    create_task(task_id, "flag off", repo_root=str(tmp_path))

    proposal_text = "===== 修改方案 =====\n摘要: unchanged behavior"

    def fake_run_tool(action, args):
        if action == "propose_code_changes":
            from tools.outcome_schema import SUCCESS_CODE_PROPOSAL_GENERATED, tool_success
            from context.tms.types import MilestoneToken
            from context.execution_state import compute_proposal_digest

            digest = compute_proposal_digest(proposal_text)
            return tool_success(
                SUCCESS_CODE_PROPOSAL_GENERATED,
                proposal_text,
                milestone=MilestoneToken.PROPOSED,
                details={"proposal_digest": digest},
            )
        return "tool ok"

    sequence = [
        (
            '{"action": "propose_code_changes", "args": '
            '{"task": "demo"}}'
        ),
        '{"action": "finish", "answer": "done"}',
    ]
    calls = {"index": 0}

    def sequenced_ask_ai(memory, agent_mode=None):
        idx = calls["index"]
        calls["index"] += 1
        return sequence[min(idx, len(sequence) - 1)]

    monkeypatch.setattr("react_agent.ask_ai", sequenced_ask_ai)
    monkeypatch.setattr("react_agent.run_tool", fake_run_tool)

    react_agent("start", task_id=task_id)

    latest = get_latest_checkpoint(task_id)
    assert latest is not None
    assert latest.mutation_state is not None
    assert latest.execution_state in ({}, None)
    assert latest.mutation_fsm in ({}, None)
