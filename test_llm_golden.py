"""Golden eval: react_agent orchestration contracts (mock LLM + spy or real run_tool)."""

import json

import config.settings as settings
import storage.checkpoint_store as checkpoint_store_module
import storage.task_store as task_store_module
import tools.tool_manager as tool_manager_module
from config.agent_mode import AGENT_MODE_FULL, AGENT_MODE_READONLY
from context.execution_state import PATCH_SUCCESS_MARKER
from context.mutation_fsm import (
    MutationWorkflowState,
    reset_mutation_fsm,
)
from context.project_context import set_backup_info
from react_agent import react_agent
from storage.task_store import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_COMPLETED,
    create_task,
    get_task,
    mark_task_cancelled,
    request_cancel,
)

MUTATION_TOOLS = frozenset({
    "git_create_backup",
    "write_repo_file",
    "git_rollback",
    "apply_patch",
})

_DEDUP_GOLDEN_BACKUP_BRANCH = "agent-backup/20260720-125945"
_DEDUP_GOLDEN_BACKUP_COMMIT = "c626a6b"
_DEDUP_GOLDEN_PROPOSAL_DIGEST = "digest1234567890ab"


def _tool_result_messages(memory):
    return [
        item["content"]
        for item in memory
        if item.get("role") == "user"
        and str(item.get("content", "")).startswith("工具执行结果")
    ]


def _load_audit_events(path):
    if not path.exists():
        return []

    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def _patch_fsm_golden_env(
    tmp_path,
    monkeypatch,
    *,
    structured_reject=False,
):
    audit_file = _patch_dedup_golden_env(
        tmp_path,
        monkeypatch,
        dedup_enabled=False,
    )
    monkeypatch.setattr(settings, "MUTATION_FSM_ENABLED", True)
    monkeypatch.setattr(settings, "TMS_RUNTIME_SOT_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "STRUCTURED_TOOL_REJECT_ENABLED",
        structured_reject,
    )
    monkeypatch.setattr(
        tool_manager_module,
        "is_tool_confirm_skipped",
        lambda: True,
    )
    reset_mutation_fsm()
    return audit_file


def _assert_fsm_blocked(tool_results):
    assert any(
        "Mutation workflow blocked:" in text
        or "mutation_fsm_blocked" in text
        for text in tool_results
    )


def _assert_no_patch_success_audit(audit_file):
    events = _load_audit_events(audit_file)
    patch_success = [
        event
        for event in events
        if event.get("event") == "tool_call"
        and event.get("tool") == "apply_patch"
        and event.get("status") == "success"
        and PATCH_SUCCESS_MARKER in str(event.get("result", ""))
    ]
    assert patch_success == []


_FSM_PROPOSAL_TEXT = "修改方案\nsummary: golden fsm legal chain"
_FSM_DIFF_TEXT = "Unified diff preview\n--- a/sample.txt"
_FSM_BACKUP_TEXT = "Git 备份完成\nbranch: agent-backup/golden-fsm"
_FSM_PATCH_TEXT = "Patch 应用完成\npath: sample.txt"


def _tool_actions_from_memory(memory):
    actions = []
    for item in memory:
        if item.get("role") != "assistant":
            continue
        content = str(item.get("content", ""))
        if not content.startswith("{"):
            continue
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            continue
        action = payload.get("action")
        if action:
            actions.append(action)
    return actions


def _install_recording_real_run_tool(monkeypatch, recorder):
    from tools.tool_manager import run_tool as real_run_tool

    def recording_run_tool(action, args):
        recorder.append(
            {
                "action": action,
                "args": dict(args) if args else {},
            }
        )
        return real_run_tool(action, args)

    monkeypatch.setattr("react_agent.run_tool", recording_run_tool)


def _install_fsm_legal_chain_tool_stubs(monkeypatch):
    def patch_tool(name, fn):
        tool = dict(tool_manager_module.TOOLS[name])
        tool["function"] = fn
        monkeypatch.setitem(tool_manager_module.TOOLS, name, tool)

    patch_tool("propose_code_changes", lambda **kwargs: _FSM_PROPOSAL_TEXT)
    patch_tool(
        "generate_unified_diff",
        lambda **kwargs: _FSM_DIFF_TEXT,
    )
    patch_tool("git_create_backup", lambda **kwargs: _FSM_BACKUP_TEXT)
    patch_tool("apply_patch", lambda **kwargs: _FSM_PATCH_TEXT)


def _patch_dedup_golden_env(tmp_path, monkeypatch, *, dedup_enabled=True):
    db_file = tmp_path / "tasks.db"
    audit_file = tmp_path / "audit.jsonl"
    backup_file = tmp_path / "last_backup.json"

    monkeypatch.setattr(settings, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", audit_file)
    monkeypatch.setattr(settings, "BACKUP_STATE_FILE", backup_file)
    monkeypatch.setattr(settings, "CHECKPOINT_ENABLED", True)
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", dedup_enabled)
    # Dedup resume goldens isolate idempotency; FSM default-on would block apply first.
    monkeypatch.setattr(settings, "MUTATION_FSM_ENABLED", False)

    monkeypatch.setattr(task_store_module, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(checkpoint_store_module, "TASK_DB_FILE", db_file)

    import audit.audit_log as audit_log_module
    import context.project_context as project_context_module

    monkeypatch.setattr(project_context_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(project_context_module, "BACKUP_STATE_FILE", backup_file)
    monkeypatch.setattr(audit_log_module, "AUDIT_LOG_FILE", audit_file)
    project_context_module._last_backup_branch = None
    project_context_module._last_backup_commit = None
    project_context_module._last_original_branch = None

    if audit_file.exists():
        audit_file.unlink()

    return audit_file


def _seed_post_apply_resume_state(task_id, repo_root):
    set_backup_info(
        backup_branch=_DEDUP_GOLDEN_BACKUP_BRANCH,
        backup_commit=_DEDUP_GOLDEN_BACKUP_COMMIT,
        original_branch="master",
    )

    create_task(task_id, "dedup golden resume", repo_root=str(repo_root))
    mark_task_cancelled(task_id)

    initial_memory = [
        {"role": "user", "content": "modify sample.txt"},
        {
            "role": "assistant",
            "content": '{"action": "git_create_backup", "args": {}}',
        },
        {"role": "user", "content": "工具执行结果:\nGit 备份完成"},
        {
            "role": "assistant",
            "content": (
                '{"action": "apply_patch", "args": '
                '{"path": "sample.txt", "new_content": "demo\\n"}}'
            ),
        },
        {
            "role": "user",
            "content": "工具执行结果:\nPatch 应用完成\n路径: sample.txt",
        },
    ]

    initial_execution_state = {
        "proposal_digest": _DEDUP_GOLDEN_PROPOSAL_DIGEST,
        "backup_branch": _DEDUP_GOLDEN_BACKUP_BRANCH,
        "backup_commit": _DEDUP_GOLDEN_BACKUP_COMMIT,
        "patch_applied": True,
        "patch_applied_paths": ["sample.txt"],
    }

    return initial_memory, initial_execution_state


def _patch_apply_patch_spy(monkeypatch):
    apply_called = []

    def spy_apply(**kwargs):
        apply_called.append(kwargs)
        return PATCH_SUCCESS_MARKER + "\n路径: sample.txt"

    monkeypatch.setitem(
        tool_manager_module.TOOLS["apply_patch"],
        "function",
        spy_apply,
    )
    monkeypatch.setattr(tool_manager_module, "is_tool_confirm_skipped", lambda: True)

    return apply_called


def _load_audit_events(audit_file):
    if not audit_file.is_file():
        return []

    events = []

    for line in audit_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line:
            continue

        events.append(json.loads(line))

    return events


def test_golden_readonly_analysis_no_mutation(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
):
    task_id = "golden_readonly_analysis"

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "list_repo_files", "args": '
            '{"path": "tools", "extensions": ".py"}}'
        ),
        '{"action": "finish", "answer": "listed tools py files"}',
    ])

    tool_call_spy["install"]()

    answer, _memory = react_agent(
        "列出 tools 目录下的 Python 文件",
        task_id=task_id,
        agent_mode=AGENT_MODE_READONLY,
    )

    actions = [call["action"] for call in tool_call_spy["calls"]]

    assert actions == ["list_repo_files"]

    assert not MUTATION_TOOLS.intersection(actions)

    assert mock_ask_ai_sequence["count"] == 2

    assert answer == "listed tools py files"

    task = get_task(task_id)

    assert task is not None

    assert task["status"] == TASK_STATUS_COMPLETED

    assert task["agent_mode"] == AGENT_MODE_READONLY


def test_golden_full_proposal_without_mutation(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
):
    task_id = "golden_proposal_only"

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "propose_code_changes", "args": '
            '{"task": "add structured logging to run_tool"}}'
        ),
        '{"action": "finish", "answer": "proposal delivered"}',
    ])

    tool_call_spy["install"]()

    answer, _memory = react_agent(
        "给 run_tool 增加更详细的错误日志，先出方案",
        task_id=task_id,
        agent_mode=AGENT_MODE_FULL,
    )

    actions = [call["action"] for call in tool_call_spy["calls"]]

    assert actions == ["propose_code_changes"]

    assert not MUTATION_TOOLS.intersection(actions)

    assert mock_ask_ai_sequence["count"] == 2

    assert answer == "proposal delivered"

    task = get_task(task_id)

    assert task is not None

    assert task["status"] == TASK_STATUS_COMPLETED


def test_golden_full_diff_first_chain(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
):
    task_id = "golden_diff_first"

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "generate_unified_diff", "args": '
            '{"path": "sample.txt", "new_content": "updated\\n"}}'
        ),
        (
            '{"action": "git_create_backup", "args": '
            '{"message": "agent backup before change"}}'
        ),
        (
            '{"action": "apply_patch", "args": '
            '{"path": "sample.txt", "new_content": "updated\\n"}}'
        ),
        '{"action": "finish", "answer": "diff preview backup apply done"}',
    ])

    tool_call_spy["install"]()

    answer, _memory = react_agent(
        "确认执行，更新 sample.txt",
        task_id=task_id,
        agent_mode=AGENT_MODE_FULL,
    )

    actions = [call["action"] for call in tool_call_spy["calls"]]

    assert actions == [
        "generate_unified_diff",
        "git_create_backup",
        "apply_patch",
    ]

    assert mock_ask_ai_sequence["count"] == 4

    assert answer == "diff preview backup apply done"

    task = get_task(task_id)

    assert task is not None

    assert task["status"] == TASK_STATUS_COMPLETED


def test_golden_full_finish_terminates_loop(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
):
    task_id = "golden_finish_loop"

    mock_ask_ai_sequence["install"]([
        '{"action": "git_status", "args": {}}',
        '{"action": "finish", "answer": "status checked"}',
    ])

    tool_call_spy["install"]()

    answer, _memory = react_agent(
        "查看 git 状态",
        task_id=task_id,
        agent_mode=AGENT_MODE_FULL,
    )

    actions = [call["action"] for call in tool_call_spy["calls"]]

    assert actions == ["git_status"]

    assert mock_ask_ai_sequence["count"] == 2

    assert answer == "status checked"

    task = get_task(task_id)

    assert task is not None

    assert task["status"] == TASK_STATUS_COMPLETED


def test_golden_readonly_allows_diff_preview(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
):
    task_id = "golden_readonly_diff_preview"

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "generate_unified_diff", "args": '
            '{"path": "sample.txt", "new_content": "preview only\\n"}}'
        ),
        '{"action": "finish", "answer": "diff preview only"}',
    ])

    tool_call_spy["install"]()

    answer, _memory = react_agent(
        "预览 sample.txt 的 unified diff，不要写入",
        task_id=task_id,
        agent_mode=AGENT_MODE_READONLY,
    )

    actions = [call["action"] for call in tool_call_spy["calls"]]

    assert actions == ["generate_unified_diff"]

    assert "apply_patch" not in actions

    assert mock_ask_ai_sequence["count"] == 2

    assert answer == "diff preview only"

    task = get_task(task_id)

    assert task is not None

    assert task["status"] == TASK_STATUS_COMPLETED

    assert task["agent_mode"] == AGENT_MODE_READONLY


def test_golden_full_batch_diff_first_chain(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
):
    task_id = "golden_batch_diff_first"

    batch_changes = (
        '[{"path": "a.txt", "new_content": "a-updated\\n"}, '
        '{"path": "b.txt", "new_content": "b-updated\\n"}]'
    )

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "generate_unified_diff", "args": '
            '{"changes": ' + batch_changes + "}}"
        ),
        (
            '{"action": "git_create_backup", "args": '
            '{"message": "agent backup before change"}}'
        ),
        (
            '{"action": "apply_patch", "args": '
            '{"changes": ' + batch_changes + "}}"
        ),
        '{"action": "finish", "answer": "batch preview backup apply done"}',
    ])

    tool_call_spy["install"]()

    answer, _memory = react_agent(
        "确认执行，批量更新 a.txt 和 b.txt",
        task_id=task_id,
        agent_mode=AGENT_MODE_FULL,
    )

    actions = [call["action"] for call in tool_call_spy["calls"]]

    assert actions == [
        "generate_unified_diff",
        "git_create_backup",
        "apply_patch",
    ]

    preview_args = tool_call_spy["calls"][0]["args"]
    apply_args = tool_call_spy["calls"][2]["args"]

    assert len(preview_args["changes"]) == 2
    assert preview_args["changes"][0]["path"] == "a.txt"
    assert preview_args["changes"][1]["path"] == "b.txt"
    assert preview_args["changes"] == apply_args["changes"]

    assert mock_ask_ai_sequence["count"] == 4

    assert answer == "batch preview backup apply done"

    task = get_task(task_id)

    assert task is not None

    assert task["status"] == TASK_STATUS_COMPLETED


def test_golden_readonly_allows_batch_diff_preview(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
):
    task_id = "golden_readonly_batch_preview"

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "generate_unified_diff", "args": '
            '{"changes": ['
            '{"path": "a.txt", "new_content": "a-preview\\n"}, '
            '{"path": "b.txt", "new_content": "b-preview\\n"}'
            "]}}"
        ),
        '{"action": "finish", "answer": "batch diff preview only"}',
    ])

    tool_call_spy["install"]()

    answer, _memory = react_agent(
        "只读预览 a.txt 和 b.txt 的 batch diff",
        task_id=task_id,
        agent_mode=AGENT_MODE_READONLY,
    )

    actions = [call["action"] for call in tool_call_spy["calls"]]

    assert actions == ["generate_unified_diff"]

    assert len(tool_call_spy["calls"][0]["args"]["changes"]) == 2

    assert "apply_patch" not in actions

    assert not MUTATION_TOOLS.intersection(actions)

    assert mock_ask_ai_sequence["count"] == 2

    assert answer == "batch diff preview only"

    task = get_task(task_id)

    assert task is not None

    assert task["status"] == TASK_STATUS_COMPLETED

    assert task["agent_mode"] == AGENT_MODE_READONLY


def test_golden_readonly_blocks_batch_apply_patch_real_run_tool(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
):
    task_id = "golden_readonly_block_batch_apply"

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "apply_patch", "args": '
            '{"changes": ['
            '{"path": "a.txt", "new_content": "blocked-a\\n"}, '
            '{"path": "b.txt", "new_content": "blocked-b\\n"}'
            "]}}"
        ),
        '{"action": "finish", "answer": "batch mutation blocked"}',
    ])

    tool_call_spy["install"](use_real_run_tool=True)

    answer, memory = react_agent(
        "尝试 batch apply patch",
        task_id=task_id,
        agent_mode=AGENT_MODE_READONLY,
    )

    assert tool_call_spy["calls"] == []

    tool_results = _tool_result_messages(memory)

    assert len(tool_results) == 1

    assert "apply_patch" in tool_results[0]

    assert "readonly" in tool_results[0]

    assert mock_ask_ai_sequence["count"] == 2

    assert answer == "batch mutation blocked"

    task = get_task(task_id)

    assert task is not None

    assert task["status"] == TASK_STATUS_COMPLETED

    assert task["agent_mode"] == AGENT_MODE_READONLY


def test_golden_plain_text_answer_no_tool(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
):
    task_id = "golden_plain_text"

    plain = "这是无需工具的 direct answer。"

    mock_ask_ai_sequence["install"]([plain])

    tool_call_spy["install"]()

    answer, memory = react_agent(
        "简单说明 RepoPilot 是什么",
        task_id=task_id,
        agent_mode=AGENT_MODE_FULL,
    )

    assert tool_call_spy["calls"] == []

    assert mock_ask_ai_sequence["count"] == 1

    assert answer == plain

    assert memory is not None

    task = get_task(task_id)

    assert task is not None

    assert task["status"] == TASK_STATUS_COMPLETED


def test_golden_readonly_blocks_apply_patch_real_run_tool(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
):
    task_id = "golden_readonly_block_apply"

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "apply_patch", "args": '
            '{"path": "sample.txt", "new_content": "blocked\\n"}}'
        ),
        '{"action": "finish", "answer": "mutation blocked"}',
    ])

    tool_call_spy["install"](use_real_run_tool=True)

    answer, memory = react_agent(
        "尝试 apply patch",
        task_id=task_id,
        agent_mode=AGENT_MODE_READONLY,
    )

    assert tool_call_spy["calls"] == []

    tool_results = _tool_result_messages(memory)

    assert len(tool_results) == 1

    assert "apply_patch" in tool_results[0]

    assert "readonly" in tool_results[0]

    assert mock_ask_ai_sequence["count"] == 2

    assert answer == "mutation blocked"

    task = get_task(task_id)

    assert task is not None

    assert task["status"] == TASK_STATUS_COMPLETED

    assert task["agent_mode"] == AGENT_MODE_READONLY


def test_golden_readonly_blocks_git_create_backup_real_run_tool(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
):
    task_id = "golden_readonly_block_backup"

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "git_create_backup", "args": '
            '{"message": "should not run"}}'
        ),
        '{"action": "finish", "answer": "backup blocked"}',
    ])

    tool_call_spy["install"](use_real_run_tool=True)

    answer, memory = react_agent(
        "创建 git 备份",
        task_id=task_id,
        agent_mode=AGENT_MODE_READONLY,
    )

    assert tool_call_spy["calls"] == []

    tool_results = _tool_result_messages(memory)

    assert len(tool_results) == 1

    assert "git_create_backup" in tool_results[0]

    assert "readonly" in tool_results[0]

    assert mock_ask_ai_sequence["count"] == 2

    assert answer == "backup blocked"

    task = get_task(task_id)

    assert task is not None

    assert task["status"] == TASK_STATUS_COMPLETED


def test_golden_cancel_before_mutation(
    mock_ask_ai_sequence,
    isolated_task_db,
    monkeypatch,
):
    task_id = "golden_cancel_before_mutation"

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "propose_code_changes", "args": '
            '{"task": "add logging to run_tool"}}'
        ),
        (
            '{"action": "apply_patch", "args": '
            '{"path": "sample.txt", "new_content": "blocked\\n"}}'
        ),
    ])

    calls = []

    def fake_run_tool(action, args):
        calls.append(action)
        if action == "propose_code_changes":
            request_cancel(task_id)
        return action + " ok"

    monkeypatch.setattr("react_agent.run_tool", fake_run_tool)

    answer, _memory = react_agent(
        "先出方案再改 sample.txt",
        task_id=task_id,
        agent_mode=AGENT_MODE_FULL,
    )

    assert calls == ["propose_code_changes"]
    assert "apply_patch" not in calls
    assert mock_ask_ai_sequence["count"] == 1
    assert answer == "任务已取消"

    task = get_task(task_id)
    assert task is not None
    assert task["status"] == TASK_STATUS_CANCELLED


def test_golden_resume_continues_step(
    mock_ask_ai_sequence,
    isolated_task_db,
):
    task_id = "golden_resume_continues_step"

    create_task(task_id, "resume golden", repo_root="/tmp/repo")
    mark_task_cancelled(task_id)

    initial_memory = [
        {"role": "user", "content": "analyze repo"},
        {"role": "assistant", "content": '{"action": "git_status", "args": {}}'},
        {"role": "user", "content": "工具执行结果:\nbranch main"},
    ]

    mock_ask_ai_sequence["install"]([
        '{"action": "finish", "answer": "continued from checkpoint"}',
    ])

    answer, memory = react_agent(
        "",
        task_id=task_id,
        resume_from_step=1,
        initial_memory=initial_memory,
    )

    assert mock_ask_ai_sequence["count"] == 1
    assert len(memory) == 3
    assert memory[0]["content"] == "analyze repo"
    assert answer == "continued from checkpoint"

    task = get_task(task_id)
    assert task is not None
    assert task["status"] == TASK_STATUS_COMPLETED


def test_golden_resume_dedup_skips_duplicate_apply(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
    tmp_path,
    monkeypatch,
):
    task_id = "golden_resume_dedup_skip_apply"

    _patch_dedup_golden_env(tmp_path, monkeypatch, dedup_enabled=True)
    initial_memory, initial_execution_state = _seed_post_apply_resume_state(
        task_id,
        tmp_path,
    )
    apply_called = _patch_apply_patch_spy(monkeypatch)

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "apply_patch", "args": '
            '{"path": "sample.txt", "new_content": "demo\\n"}}'
        ),
        '{"action": "finish", "answer": "dedup skip apply done"}',
    ])

    tool_call_spy["install"](use_real_run_tool=True)

    answer, memory = react_agent(
        "",
        task_id=task_id,
        resume_from_step=2,
        initial_memory=initial_memory,
        initial_execution_state=initial_execution_state,
    )

    tool_results = _tool_result_messages(memory)

    assert apply_called == []
    assert any("跳过重复 apply_patch" in text for text in tool_results)
    assert any(
        item.get("content", "").startswith("[checkpoint]")
        for item in memory
        if item.get("role") == "user"
    )
    assert mock_ask_ai_sequence["count"] == 2
    assert answer == "dedup skip apply done"

    task = get_task(task_id)
    assert task is not None
    assert task["status"] == TASK_STATUS_COMPLETED

    dedup_events = [
        event
        for event in _load_audit_events(settings.AUDIT_LOG_FILE)
        if event.get("event") == "execution_state_dedup"
    ]
    assert len(dedup_events) == 1
    assert dedup_events[0]["tool"] == "apply_patch"
    assert dedup_events[0]["status"] == "skipped"


def test_golden_resume_dedup_flag_off_does_not_skip_apply(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
    tmp_path,
    monkeypatch,
):
    task_id = "golden_resume_dedup_flag_off_apply"

    _patch_dedup_golden_env(tmp_path, monkeypatch, dedup_enabled=False)
    initial_memory, initial_execution_state = _seed_post_apply_resume_state(
        task_id,
        tmp_path,
    )
    apply_called = _patch_apply_patch_spy(monkeypatch)

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "apply_patch", "args": '
            '{"path": "sample.txt", "new_content": "demo\\n"}}'
        ),
        '{"action": "finish", "answer": "dedup flag off apply ran"}',
    ])

    tool_call_spy["install"](use_real_run_tool=True)

    answer, memory = react_agent(
        "",
        task_id=task_id,
        resume_from_step=2,
        initial_memory=initial_memory,
        initial_execution_state=initial_execution_state,
    )

    tool_results = _tool_result_messages(memory)

    assert len(apply_called) == 1
    assert apply_called[0]["path"] == "sample.txt"
    assert not any("跳过重复 apply_patch" in text for text in tool_results)
    assert not any(
        item.get("content", "").startswith("[checkpoint]")
        for item in memory
        if item.get("role") == "user"
    )
    assert mock_ask_ai_sequence["count"] == 2
    assert answer == "dedup flag off apply ran"

    task = get_task(task_id)
    assert task is not None
    assert task["status"] == TASK_STATUS_COMPLETED

    dedup_events = [
        event
        for event in _load_audit_events(settings.AUDIT_LOG_FILE)
        if event.get("event") == "execution_state_dedup"
    ]
    assert dedup_events == []


def test_golden_readonly_cancel_safe(
    mock_ask_ai_sequence,
    isolated_task_db,
    monkeypatch,
):
    task_id = "golden_readonly_cancel_safe"

    mock_ask_ai_sequence["install"]([
        '{"action": "git_status", "args": {}}',
        (
            '{"action": "apply_patch", "args": '
            '{"path": "sample.txt", "new_content": "blocked\\n"}}'
        ),
    ])

    calls = []

    def fake_run_tool(action, args):
        calls.append(action)
        request_cancel(task_id)
        return action + " ok"

    monkeypatch.setattr("react_agent.run_tool", fake_run_tool)

    answer, _memory = react_agent(
        "只读分析后不要写入",
        task_id=task_id,
        agent_mode=AGENT_MODE_READONLY,
    )

    assert calls == ["git_status"]
    assert "apply_patch" not in calls
    assert mock_ask_ai_sequence["count"] == 1
    assert answer == "任务已取消"

    task = get_task(task_id)
    assert task is not None
    assert task["status"] == TASK_STATUS_CANCELLED
    assert task["agent_mode"] == AGENT_MODE_READONLY


def test_golden_readonly_search_in_repo_orchestration(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
):
    task_id = "golden_readonly_search_in_repo"

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "search_in_repo", "args": '
            '{"keyword": "context budget", "extensions": ".py"}}'
        ),
        '{"action": "finish", "answer": "search completed"}',
    ])

    tool_call_spy["install"]()

    answer, _memory = react_agent(
        "搜索仓库里 context budget 相关代码",
        task_id=task_id,
        agent_mode=AGENT_MODE_READONLY,
    )

    actions = [call["action"] for call in tool_call_spy["calls"]]

    assert actions == ["search_in_repo"]
    assert not MUTATION_TOOLS.intersection(actions)
    assert mock_ask_ai_sequence["count"] == 2
    assert answer == "search completed"

    task = get_task(task_id)
    assert task is not None
    assert task["status"] == TASK_STATUS_COMPLETED
    assert task["agent_mode"] == AGENT_MODE_READONLY


def test_golden_readonly_search_then_symbol_lookup(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
):
    task_id = "golden_readonly_search_symbol_chain"

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "search_in_repo", "args": '
            '{"keyword": "react_agent", "extensions": ".py"}}'
        ),
        (
            '{"action": "find_file_dependencies", "args": '
            '{"symbol": "react_agent", "query_mode": "symbol"}}'
        ),
        '{"action": "finish", "answer": "analysis chain done"}',
    ])

    tool_call_spy["install"]()

    answer, _memory = react_agent(
        "先搜索 react_agent，再查 symbol 引用",
        task_id=task_id,
        agent_mode=AGENT_MODE_READONLY,
    )

    actions = [call["action"] for call in tool_call_spy["calls"]]

    assert actions == ["search_in_repo", "find_file_dependencies"]
    assert not MUTATION_TOOLS.intersection(actions)
    assert mock_ask_ai_sequence["count"] == 3
    assert answer == "analysis chain done"

    task = get_task(task_id)
    assert task is not None
    assert task["status"] == TASK_STATUS_COMPLETED


def test_golden_fsm_apply_before_backup(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
    isolated_repo_paths,
    monkeypatch,
    tmp_path,
):
    audit_file = _patch_fsm_golden_env(tmp_path, monkeypatch)
    task_id = "golden_fsm_apply_before_backup"

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "apply_patch", "args": '
            '{"path": "sample.txt", "new_content": "blocked\\n"}}'
        ),
        '{"action": "finish", "answer": "fsm blocked apply"}',
    ])

    tool_call_spy["install"](use_real_run_tool=True)
    recorded_calls = []
    _install_recording_real_run_tool(monkeypatch, recorded_calls)

    answer, memory = react_agent(
        "直接 apply patch",
        task_id=task_id,
        agent_mode=AGENT_MODE_FULL,
    )

    tool_results = _tool_result_messages(memory)

    assert len(recorded_calls) == 1
    assert recorded_calls[0]["action"] == "apply_patch"
    assert len(tool_results) == 1
    _assert_fsm_blocked(tool_results)
    _assert_no_patch_success_audit(audit_file)
    assert any(
        event.get("event") == "mutation_fsm_blocked"
        for event in _load_audit_events(audit_file)
    )
    assert mock_ask_ai_sequence["count"] == 2
    assert answer == "fsm blocked apply"


def test_golden_fsm_backup_before_propose(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
    isolated_repo_paths,
    monkeypatch,
    tmp_path,
):
    audit_file = _patch_fsm_golden_env(tmp_path, monkeypatch)
    task_id = "golden_fsm_backup_before_propose"

    mock_ask_ai_sequence["install"]([
        '{"action": "git_create_backup", "args": {"message": "too early"}}',
        '{"action": "finish", "answer": "fsm blocked backup"}',
    ])

    tool_call_spy["install"](use_real_run_tool=True)
    recorded_calls = []
    _install_recording_real_run_tool(monkeypatch, recorded_calls)

    answer, memory = react_agent(
        "未 propose 就备份",
        task_id=task_id,
        agent_mode=AGENT_MODE_FULL,
    )

    tool_results = _tool_result_messages(memory)

    assert len(recorded_calls) == 1
    assert recorded_calls[0]["action"] == "git_create_backup"
    assert len(tool_results) == 1
    _assert_fsm_blocked(tool_results)
    assert any(
        event.get("event") == "mutation_fsm_blocked"
        and event.get("tool") == "git_create_backup"
        for event in _load_audit_events(audit_file)
    )
    assert mock_ask_ai_sequence["count"] == 2
    assert answer == "fsm blocked backup"


def test_golden_fsm_diff_before_propose(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
    isolated_repo_paths,
    monkeypatch,
    tmp_path,
):
    _patch_fsm_golden_env(tmp_path, monkeypatch)
    task_id = "golden_fsm_diff_before_propose"

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "generate_unified_diff", "args": '
            '{"path": "sample.txt", "new_content": "blocked\\n"}}'
        ),
        '{"action": "finish", "answer": "fsm blocked diff"}',
    ])

    tool_call_spy["install"](use_real_run_tool=True)
    recorded_calls = []
    _install_recording_real_run_tool(monkeypatch, recorded_calls)

    answer, memory = react_agent(
        "未 propose 就预览 diff",
        task_id=task_id,
        agent_mode=AGENT_MODE_FULL,
    )

    tool_results = _tool_result_messages(memory)

    assert len(recorded_calls) == 1
    assert recorded_calls[0]["action"] == "generate_unified_diff"
    assert len(tool_results) == 1
    _assert_fsm_blocked(tool_results)
    assert mock_ask_ai_sequence["count"] == 2
    assert answer == "fsm blocked diff"


def test_golden_fsm_write_repo_blocked_on_diff_first_path(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
    isolated_repo_paths,
    monkeypatch,
    tmp_path,
):
    _patch_fsm_golden_env(tmp_path, monkeypatch)
    task_id = "golden_fsm_write_on_diff_first"

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "propose_code_changes", "args": '
            '{"task": "update sample.txt"}}'
        ),
        (
            '{"action": "generate_unified_diff", "args": '
            '{"path": "sample.txt", "new_content": "updated\\n"}}'
        ),
        (
            '{"action": "write_repo_file", "args": '
            '{"path": "sample.txt", "content": "updated\\n"}}'
        ),
        '{"action": "finish", "answer": "write blocked on diff-first"}',
    ])

    _install_fsm_legal_chain_tool_stubs(monkeypatch)
    tool_call_spy["install"](use_real_run_tool=True)
    recorded_calls = []
    _install_recording_real_run_tool(monkeypatch, recorded_calls)

    answer, memory = react_agent(
        "diff-first 路径误用 write_repo_file",
        task_id=task_id,
        agent_mode=AGENT_MODE_FULL,
    )

    actions = [call["action"] for call in recorded_calls]
    tool_results = _tool_result_messages(memory)

    assert actions == [
        "propose_code_changes",
        "generate_unified_diff",
        "write_repo_file",
    ]
    assert len(tool_results) == 3
    _assert_fsm_blocked([tool_results[-1]])
    assert mock_ask_ai_sequence["count"] == 4
    assert answer == "write blocked on diff-first"


def test_golden_fsm_legal_diff_chain(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
    isolated_repo_paths,
    monkeypatch,
    tmp_path,
):
    _patch_fsm_golden_env(tmp_path, monkeypatch)
    task_id = "golden_fsm_legal_diff_chain"

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "propose_code_changes", "args": '
            '{"task": "update sample.txt"}}'
        ),
        (
            '{"action": "generate_unified_diff", "args": '
            '{"path": "sample.txt", "new_content": "updated\\n"}}'
        ),
        '{"action": "git_create_backup", "args": {"message": "agent backup"}}',
        (
            '{"action": "apply_patch", "args": '
            '{"path": "sample.txt", "new_content": "updated\\n"}}'
        ),
        '{"action": "finish", "answer": "fsm legal chain done"}',
    ])

    _install_fsm_legal_chain_tool_stubs(monkeypatch)
    tool_call_spy["install"](use_real_run_tool=True)
    recorded_calls = []
    _install_recording_real_run_tool(monkeypatch, recorded_calls)

    answer, memory = react_agent(
        "合法 diff-first 全链",
        task_id=task_id,
        agent_mode=AGENT_MODE_FULL,
    )

    actions = [call["action"] for call in recorded_calls]
    tool_results = _tool_result_messages(memory)

    assert actions == [
        "propose_code_changes",
        "generate_unified_diff",
        "git_create_backup",
        "apply_patch",
    ]
    assert len(tool_results) == 4
    assert not any("Mutation workflow blocked:" in text for text in tool_results)
    from context.tms.context import get_shadow

    shadow = get_shadow()
    assert shadow.workflow.state == MutationWorkflowState.PATCHED
    assert mock_ask_ai_sequence["count"] == 5
    assert answer == "fsm legal chain done"


def test_golden_fsm_structured_reject_contract(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
    isolated_repo_paths,
    monkeypatch,
    tmp_path,
):
    audit_file = _patch_fsm_golden_env(
        tmp_path,
        monkeypatch,
        structured_reject=True,
    )
    task_id = "golden_fsm_structured_reject"

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "apply_patch", "args": '
            '{"path": "sample.txt", "new_content": "blocked\\n"}}'
        ),
        '{"action": "finish", "answer": "structured fsm reject"}',
    ])

    tool_call_spy["install"](use_real_run_tool=True)

    answer, memory = react_agent(
        "structured reject contract",
        task_id=task_id,
        agent_mode=AGENT_MODE_FULL,
    )

    tool_results = _tool_result_messages(memory)

    assert len(tool_results) == 1
    assert "Mutation workflow blocked:" in tool_results[0]
    assert "<!-- tool_reject" not in tool_results[0]
    assert '"ok": false' not in tool_results[0]

    events = _load_audit_events(audit_file)
    tool_calls = [event for event in events if event.get("event") == "tool_call"]
    assert tool_calls[0]["reject_code"] == "mutation_fsm_blocked"
    assert tool_calls[0]["reject_details"]["current_state"] == "ANALYZING"
    assert any(event.get("event") == "mutation_fsm_blocked" for event in events)
    assert mock_ask_ai_sequence["count"] == 2
    assert answer == "structured fsm reject"


def test_golden_verify_change_after_legal_patch_chain(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
    isolated_repo_paths,
    monkeypatch,
    tmp_path,
):
    """Full soft loop: propose→diff→backup→apply→verify→finish under default FSM."""
    _patch_fsm_golden_env(tmp_path, monkeypatch)
    (tmp_path / "sample.py").write_text("x = 1\n", encoding="utf-8")
    task_id = "golden_verify_after_patch"

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "propose_code_changes", "args": '
            '{"task": "update sample.py"}}'
        ),
        (
            '{"action": "generate_unified_diff", "args": '
            '{"path": "sample.py", "new_content": "x = 2\\n"}}'
        ),
        '{"action": "git_create_backup", "args": {"message": "agent backup"}}',
        (
            '{"action": "apply_patch", "args": '
            '{"path": "sample.py", "new_content": "x = 2\\n"}}'
        ),
        '{"action": "verify_change", "args": {}}',
        '{"action": "finish", "answer": "verify loop done"}',
    ])

    _install_fsm_legal_chain_tool_stubs(monkeypatch)

    def fake_apply(**kwargs):
        path = kwargs.get("path") or "sample.py"
        content = kwargs.get("new_content") or "x = 2\n"
        (tmp_path / path).write_text(content, encoding="utf-8")
        return _FSM_PATCH_TEXT

    tool = dict(tool_manager_module.TOOLS["apply_patch"])
    tool["function"] = fake_apply
    monkeypatch.setitem(tool_manager_module.TOOLS, "apply_patch", tool)

    tool_call_spy["install"](use_real_run_tool=True)
    recorded_calls = []
    _install_recording_real_run_tool(monkeypatch, recorded_calls)

    answer, memory = react_agent(
        "改码并验证",
        task_id=task_id,
        agent_mode=AGENT_MODE_FULL,
    )

    actions = [call["action"] for call in recorded_calls]
    tool_results = _tool_result_messages(memory)

    assert actions == [
        "propose_code_changes",
        "generate_unified_diff",
        "git_create_backup",
        "apply_patch",
        "verify_change",
    ]
    assert any("verify_passed" in text or "验证通过" in text for text in tool_results)
    from context.tms.context import get_shadow
    from context.tms.types import VerificationStatus

    shadow = get_shadow()
    assert shadow.workflow.state == MutationWorkflowState.PATCHED
    assert shadow.verification.status == VerificationStatus.PASSED
    assert answer == "verify loop done"


def test_golden_verify_change_failure_keeps_patched(
    mock_ask_ai_sequence,
    tool_call_spy,
    isolated_task_db,
    isolated_repo_paths,
    monkeypatch,
    tmp_path,
):
    _patch_fsm_golden_env(tmp_path, monkeypatch)
    task_id = "golden_verify_failed_keeps_patched"

    from context.tms import export_mutation_state_for_checkpoint, reset_mutation_state
    from context.tms.context import get_shadow
    from context.tms.types import MutationPath, VerificationStatus

    reset_mutation_state()
    shadow = get_shadow()
    shadow.workflow.state = MutationWorkflowState.PATCHED
    shadow.workflow.path = MutationPath.DIFF_FIRST
    shadow.artifacts.patch_applied = True
    shadow.artifacts.patch_applied_paths = ["broken.py"]
    (tmp_path / "broken.py").write_text("def bad(\n", encoding="utf-8")
    mutation_blob = export_mutation_state_for_checkpoint()

    create_task(task_id, "verify failure golden", repo_root=str(tmp_path))
    mark_task_cancelled(task_id)

    mock_ask_ai_sequence["install"]([
        (
            '{"action": "verify_change", "args": '
            '{"checks": "syntax", "paths": "broken.py"}}'
        ),
        '{"action": "finish", "answer": "verify failed but finished"}',
    ])
    tool_call_spy["install"](use_real_run_tool=True)

    answer, memory = react_agent(
        "",
        task_id=task_id,
        resume_from_step=1,
        initial_memory=[{"role": "user", "content": "verify broken syntax"}],
        initial_mutation_state=mutation_blob,
        agent_mode=AGENT_MODE_FULL,
    )

    tool_results = _tool_result_messages(memory)
    assert any("verify_failed" in text or "验证失败" in text for text in tool_results)
    shadow = get_shadow()
    assert shadow.workflow.state == MutationWorkflowState.PATCHED
    assert shadow.verification.status == VerificationStatus.FAILED
    assert answer == "verify failed but finished"
