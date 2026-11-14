"""M5-c checkpoint save v2-only tests (PR-M5-c)."""


import config.settings as settings
from context.execution_state import compute_proposal_digest
from context.tms.types import MilestoneToken
from storage.checkpoint_store import get_latest_checkpoint
from storage.task_store import create_task
from tools.outcome_schema import SUCCESS_CODE_PROPOSAL_GENERATED, tool_success


def _patch_agent_dbs(tmp_path, monkeypatch):
    db_file = tmp_path / "tasks.db"
    audit_file = tmp_path / "audit.jsonl"
    monkeypatch.setattr(settings, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", audit_file)
    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(settings, "CHECKPOINT_ENABLED", True)

    import storage.task_store as task_store_module
    import storage.checkpoint_store as checkpoint_store_module
    import audit.audit_log as audit_log_module

    monkeypatch.setattr(task_store_module, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(checkpoint_store_module, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(audit_log_module, "AUDIT_LOG_FILE", audit_file)


def test_react_checkpoint_save_v2_only_omits_v1_columns(tmp_path, monkeypatch):
    _patch_agent_dbs(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "CHECKPOINT_MUTATION_STATE_V2_ENABLED", False)

    from react_agent import react_agent

    task_id = "m5c-v2-only-save"
    create_task(task_id, "v2 only", repo_root=str(tmp_path))

    proposal_text = "===== 修改方案 =====\n摘要: v2 save"

    def fake_run_tool(action, args):
        if action == "propose_code_changes":
            digest = compute_proposal_digest(proposal_text)
            return tool_success(
                SUCCESS_CODE_PROPOSAL_GENERATED,
                proposal_text,
                milestone=MilestoneToken.PROPOSED,
                details={"proposal_digest": digest},
            )
        return "tool ok"

    sequence = [
        '{"action": "propose_code_changes", "args": {"task": "v2 save"}}',
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
    assert latest.execution_state in ({}, None)
    assert latest.mutation_fsm in ({}, None)
