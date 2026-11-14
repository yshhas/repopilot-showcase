import pytest

import config.settings as settings
import tools.tool_manager as tool_manager_module
from audit.context import reset_agent_mode, set_agent_mode
from config.agent_mode import AGENT_MODE_FULL, AGENT_MODE_READONLY
from context.mutation_fsm import (
    FSM_REJECT_CODE,
    MutationPath,
    MutationWorkflowState,
    advance_mutation_fsm_on_success,
    check_mutation_fsm_allowed,
    get_mutation_fsm_context,
    is_fsm_reject_result,
    mark_mutation_fsm_done,
    reset_mutation_fsm,
)
from tools.result_schema import tool_result_message
from tools.tool_manager import run_tool


PROPOSAL_TEXT = "修改方案\nsummary: test"
DIFF_TEXT = "Unified diff preview\n--- a/sample.txt"
BACKUP_TEXT = "Git 备份完成\nbranch: agent-backup/test"
PATCH_TEXT = "Patch 应用完成\npath: sample.txt"
WRITE_TEXT = "文件写入完成\npath: sample.txt"
ROLLBACK_TEXT = "Git 回滚完成\nrestored"


@pytest.fixture(autouse=True)
def _reset_runtime_state():
    from context.execution_state import reset_execution_state
    from context.tms import reset_mutation_state

    reset_execution_state()
    reset_mutation_fsm()
    reset_mutation_state()
    yield
    reset_execution_state()
    reset_mutation_fsm()
    reset_mutation_state()


def _seed_tms_diff_first_backup():
    from context.execution_state import compute_proposal_digest
    from context.tms import MilestoneToken, advance_from_outcome, reset_mutation_state
    from tools.outcome_schema import (
        SUCCESS_CODE_BACKUP_CREATED,
        SUCCESS_CODE_DIFF_GENERATED,
        SUCCESS_CODE_PROPOSAL_GENERATED,
        tool_success,
    )

    digest = compute_proposal_digest(PROPOSAL_TEXT)
    reset_mutation_state()
    advance_from_outcome(
        tool_success(
            SUCCESS_CODE_PROPOSAL_GENERATED,
            PROPOSAL_TEXT,
            milestone=MilestoneToken.PROPOSED,
            details={"proposal_digest": digest},
        ),
        tool="propose_code_changes",
        args={"task": "x"},
    )
    advance_from_outcome(
        tool_success(
            SUCCESS_CODE_DIFF_GENERATED,
            DIFF_TEXT,
            milestone=MilestoneToken.DIFF_GENERATED,
            details={"paths": ["sample.txt"]},
        ),
        tool="generate_unified_diff",
        args={"path": "sample.txt", "new_content": "updated\n"},
    )
    advance_from_outcome(
        tool_success(
            SUCCESS_CODE_BACKUP_CREATED,
            BACKUP_TEXT,
            milestone=MilestoneToken.BACKUP_CREATED,
            details={
                "backup_branch": "agent-backup/test",
                "backup_commit": "abc1234",
                "original_branch": "main",
            },
        ),
        tool="git_create_backup",
        args={},
    )


def _advance_proposed():
    advance_mutation_fsm_on_success("propose_code_changes", {}, PROPOSAL_TEXT)


def _enable_fsm(monkeypatch):
    monkeypatch.setattr(settings, "MUTATION_FSM_ENABLED", True)
    reset_mutation_fsm()


def _disable_fsm(monkeypatch):
    monkeypatch.setattr(settings, "MUTATION_FSM_ENABLED", False)
    reset_mutation_fsm()


@pytest.fixture
def fsm_enabled(monkeypatch):
    _enable_fsm(monkeypatch)
    yield
    reset_mutation_fsm()


def _advance_proposed():
    advance_mutation_fsm_on_success("propose_code_changes", {}, PROPOSAL_TEXT)


def _advance_diff_first_preview():
    _advance_proposed()
    advance_mutation_fsm_on_success(
        "generate_unified_diff",
        {"path": "sample.txt", "new_content": "updated\n"},
        DIFF_TEXT,
    )


def _advance_diff_first_backup():
    _advance_diff_first_preview()
    advance_mutation_fsm_on_success("git_create_backup", {}, BACKUP_TEXT)
    _seed_tms_diff_first_backup()


def _advance_write_fallback_backup():
    _advance_proposed()
    advance_mutation_fsm_on_success("git_create_backup", {}, BACKUP_TEXT)


def test_flag_disabled_check_is_noop(monkeypatch):
    _disable_fsm(monkeypatch)

    reject = check_mutation_fsm_allowed(
        "apply_patch",
        {"path": "sample.txt", "new_content": "x"},
        agent_mode=AGENT_MODE_FULL,
    )

    assert reject is None


def test_flag_disabled_run_tool_allows_out_of_order_apply(monkeypatch):
    _disable_fsm(monkeypatch)
    mode_token = set_agent_mode(AGENT_MODE_FULL)

    called = {"count": 0}

    def fake_apply(**kwargs):
        called["count"] += 1
        return PATCH_TEXT

    monkeypatch.setitem(
        tool_manager_module.TOOLS["apply_patch"],
        "function",
        fake_apply,
    )
    monkeypatch.setattr(tool_manager_module, "is_tool_confirm_skipped", lambda: True)

    result = run_tool(
        "apply_patch",
        {"path": "sample.txt", "new_content": "updated\n"},
    )

    reset_agent_mode(mode_token)

    assert called["count"] == 1
    assert not is_fsm_reject_result(result)


def test_diff_first_legal_chain_advances_to_patched(fsm_enabled):
    reset_mutation_fsm()
    _advance_diff_first_backup()
    ctx = get_mutation_fsm_context()

    assert ctx.state == MutationWorkflowState.BACKED_UP
    assert ctx.mutation_path == MutationPath.DIFF_FIRST

    advance_mutation_fsm_on_success(
        "apply_patch",
        {"path": "sample.txt", "new_content": "updated\n"},
        PATCH_TEXT,
    )

    ctx = get_mutation_fsm_context()
    assert ctx.state == MutationWorkflowState.PATCHED
    assert ctx.mutation_path == MutationPath.DIFF_FIRST


def test_repreview_stays_diff_previewed(fsm_enabled):
    _advance_diff_first_preview()
    advance_mutation_fsm_on_success(
        "generate_unified_diff",
        {"path": "sample.txt", "new_content": "updated\n"},
        DIFF_TEXT,
    )

    ctx = get_mutation_fsm_context()
    assert ctx.state == MutationWorkflowState.DIFF_PREVIEWED
    assert ctx.mutation_path == MutationPath.DIFF_FIRST


def test_rebackup_stays_backed_up_on_diff_first(fsm_enabled):
    _advance_diff_first_backup()
    advance_mutation_fsm_on_success("git_create_backup", {}, BACKUP_TEXT)

    ctx = get_mutation_fsm_context()
    assert ctx.state == MutationWorkflowState.BACKED_UP
    assert ctx.mutation_path == MutationPath.DIFF_FIRST


def test_generate_unified_diff_rejects_from_analyzing(fsm_enabled):
    reset_mutation_fsm()

    reject = check_mutation_fsm_allowed(
        "generate_unified_diff",
        {"path": "sample.txt", "new_content": "x"},
        agent_mode=AGENT_MODE_FULL,
    )

    assert reject is not None
    assert reject["code"] == FSM_REJECT_CODE


def test_write_fallback_backup_allowed_from_proposed(fsm_enabled):
    _advance_proposed()

    reject = check_mutation_fsm_allowed(
        "git_create_backup",
        {},
        agent_mode=AGENT_MODE_FULL,
    )

    assert reject is None


def test_git_create_backup_rejects_from_analyzing(fsm_enabled):
    reset_mutation_fsm()

    reject = check_mutation_fsm_allowed(
        "git_create_backup",
        {},
        agent_mode=AGENT_MODE_FULL,
    )

    assert reject is not None
    assert "PROPOSED" in reject["message"] or "DIFF_PREVIEWED" in reject["message"]


def test_apply_patch_rejects_from_proposed(fsm_enabled):
    _advance_proposed()

    reject = check_mutation_fsm_allowed(
        "apply_patch",
        {"path": "sample.txt", "new_content": "x"},
        agent_mode=AGENT_MODE_FULL,
    )

    assert reject is not None
    assert "BACKED_UP" in reject["message"]


def test_apply_patch_rejects_from_diff_previewed(fsm_enabled):
    _advance_diff_first_preview()

    reject = check_mutation_fsm_allowed(
        "apply_patch",
        {"path": "sample.txt", "new_content": "x"},
        agent_mode=AGENT_MODE_FULL,
    )

    assert reject is not None
    assert "BACKED_UP" in reject["message"]


def test_apply_patch_rejects_on_write_fallback_path(fsm_enabled):
    _advance_write_fallback_backup()

    reject = check_mutation_fsm_allowed(
        "apply_patch",
        {"path": "sample.txt", "new_content": "x"},
        agent_mode=AGENT_MODE_FULL,
    )

    assert reject is not None
    assert "DIFF_FIRST" in reject["message"]


def test_write_fallback_legal_chain(fsm_enabled):
    reset_mutation_fsm()
    _advance_write_fallback_backup()
    ctx = get_mutation_fsm_context()

    assert ctx.state == MutationWorkflowState.BACKED_UP
    assert ctx.mutation_path == MutationPath.WRITE_FALLBACK

    advance_mutation_fsm_on_success(
        "write_repo_file",
        {"path": "sample.txt", "content": "updated\n"},
        WRITE_TEXT,
    )

    ctx = get_mutation_fsm_context()
    assert ctx.state == MutationWorkflowState.PATCHED


def test_write_repo_file_rejects_after_diff_preview(fsm_enabled):
    _advance_diff_first_preview()

    reject = check_mutation_fsm_allowed(
        "write_repo_file",
        {"path": "sample.txt", "content": "x"},
        agent_mode=AGENT_MODE_FULL,
    )

    assert reject is not None
    assert "DIFF_FIRST" in reject["message"] or "WRITE_FALLBACK" in reject["message"]


def test_generate_unified_diff_rejects_on_write_fallback_path(fsm_enabled):
    _advance_write_fallback_backup()

    reject = check_mutation_fsm_allowed(
        "generate_unified_diff",
        {"path": "sample.txt", "new_content": "x"},
        agent_mode=AGENT_MODE_FULL,
    )

    assert reject is not None
    assert "WRITE_FALLBACK" in reject["message"]


def test_apply_patch_rejects_on_write_fallback_path_after_backup(fsm_enabled):
    _advance_write_fallback_backup()

    reject = check_mutation_fsm_allowed(
        "apply_patch",
        {"path": "sample.txt", "new_content": "x"},
        agent_mode=AGENT_MODE_FULL,
    )

    assert reject is not None


def test_fsm_reject_runs_before_confirm_and_tool(monkeypatch):
    _enable_fsm(monkeypatch)
    mode_token = set_agent_mode(AGENT_MODE_FULL)

    confirm_called = {"count": 0}
    tool_called = {"count": 0}

    def fake_confirm(*args, **kwargs):
        confirm_called["count"] += 1
        return True

    def fake_apply(**kwargs):
        tool_called["count"] += 1
        return PATCH_TEXT

    monkeypatch.setattr(
        tool_manager_module,
        "request_tool_confirmation",
        fake_confirm,
    )
    monkeypatch.setitem(
        tool_manager_module.TOOLS["apply_patch"],
        "function",
        fake_apply,
    )

    result = run_tool(
        "apply_patch",
        {"path": "sample.txt", "new_content": "updated\n"},
    )

    reset_agent_mode(mode_token)

    assert is_fsm_reject_result(result)
    assert confirm_called["count"] == 0
    assert tool_called["count"] == 0


def test_confirm_denied_does_not_adance_fsm(monkeypatch):
    _enable_fsm(monkeypatch)
    mode_token = set_agent_mode(AGENT_MODE_FULL)
    _advance_diff_first_backup()

    monkeypatch.setattr(
        tool_manager_module,
        "request_tool_confirmation",
        lambda *args, **kwargs: False,
    )

    result = run_tool(
        "apply_patch",
        {"path": "sample.txt", "new_content": "updated\n"},
    )

    reset_agent_mode(mode_token)

    assert "用户已取消执行工具" in tool_result_message(result)
    ctx = get_mutation_fsm_context()
    assert ctx.state == MutationWorkflowState.BACKED_UP


def test_readonly_mode_block_unchanged_with_fsm_enabled(monkeypatch):
    _enable_fsm(monkeypatch)
    mode_token = set_agent_mode(AGENT_MODE_READONLY)

    result = run_tool(
        "apply_patch",
        {"path": "sample.txt", "new_content": "updated\n"},
    )

    reset_agent_mode(mode_token)

    text = tool_result_message(result).lower()
    assert "readonly" in text or "只读" in text


def test_repropose_from_patched_resets_path(fsm_enabled):
    _advance_diff_first_backup()
    advance_mutation_fsm_on_success(
        "apply_patch",
        {"path": "sample.txt", "new_content": "updated\n"},
        PATCH_TEXT,
    )

    new_proposal = PROPOSAL_TEXT + "\nchanged intent"
    advance_mutation_fsm_on_success("propose_code_changes", {}, new_proposal)

    ctx = get_mutation_fsm_context()
    assert ctx.state == MutationWorkflowState.PROPOSED
    assert ctx.mutation_path == MutationPath.NONE


def test_repropose_new_digest_clears_path_from_diff_previewed(fsm_enabled):
    _advance_diff_first_preview()

    new_proposal = PROPOSAL_TEXT + "\nnew digest"
    advance_mutation_fsm_on_success("propose_code_changes", {}, new_proposal)

    ctx = get_mutation_fsm_context()
    assert ctx.state == MutationWorkflowState.PROPOSED
    assert ctx.mutation_path == MutationPath.NONE


def test_git_rollback_keeps_backed_up_state(fsm_enabled):
    _advance_diff_first_backup()
    advance_mutation_fsm_on_success(
        "apply_patch",
        {"path": "sample.txt", "new_content": "updated\n"},
        PATCH_TEXT,
    )

    advance_mutation_fsm_on_success("git_rollback", {}, ROLLBACK_TEXT)

    ctx = get_mutation_fsm_context()
    assert ctx.state == MutationWorkflowState.BACKED_UP


def test_mark_done_sets_terminal_state(fsm_enabled):
    _advance_proposed()

    mark_mutation_fsm_done()

    ctx = get_mutation_fsm_context()
    assert ctx.state == MutationWorkflowState.DONE

    reject = check_mutation_fsm_allowed(
        "propose_code_changes",
        {},
        agent_mode=AGENT_MODE_FULL,
    )

    assert reject is not None


def test_backup_before_propose_is_rejected(fsm_enabled):
    reset_mutation_fsm()

    reject = check_mutation_fsm_allowed(
        "git_create_backup",
        {},
        agent_mode=AGENT_MODE_FULL,
    )

    assert reject is not None


def test_diff_first_backup_after_preview_allowed(fsm_enabled):
    _advance_diff_first_preview()

    reject = check_mutation_fsm_allowed(
        "git_create_backup",
        {},
        agent_mode=AGENT_MODE_FULL,
    )

    assert reject is None
