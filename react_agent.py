import logging
import time
import uuid

from llm import ask_ai, get_last_token_usage
from observability import (
    record_agent_step_duration,
    record_llm_call,
    record_tool_call,
)
from schemas import FinishResponse, ToolCall, parse_agent_response
from tools.tool_manager import run_tool
from tools.result_schema import format_tool_result_for_display, format_tool_result_for_memory

from audit.audit_log import log_react_step
from audit.context import (
    reset_agent_mode,
    reset_confirm_callback,
    reset_task_id,
    set_agent_mode,
    set_confirm_callback,
    set_task_id,
)
from config.agent_mode import resolve_agent_mode
from config.settings import (
    REACT_KEEP_RECENT_ROUNDS,
    REACT_MAX_CONTEXT_CHARS,
    REACT_MAX_CONTEXT_TOKENS,
    REACT_MAX_STEPS,
    REPO_ROOT,
)
from storage.task_store import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_RUNNING,
    create_task,
    DEFAULT_CANCEL_ANSWER,
    get_task,
    is_cancel_requested,
    mark_task_cancelled,
    update_task,
)

logger = logging.getLogger(__name__)


def _export_context_state_for_checkpoint():
    try:
        from context.budget_state import get_context_budget_state

        state = get_context_budget_state()
        return {
            "chars_used": state.chars_used,
            "files_read": list(state.files_read),
        }
    except Exception as e:
        logger.warning("导出上下文状态失败: %s", e, exc_info=True)
        return None


def _update_execution_state_safe(task_id, action, args, result):
    try:
        from context.tms import advance_from_outcome
        from tools.outcome_schema import normalize_tool_outcome

        outcome = normalize_tool_outcome(result, tool=action, args=args or {})
        advance_from_outcome(outcome, tool=action, args=args or {})
    except Exception as exc:
        log_react_step(
            "execution_state_update_failed",
            task_id=task_id,
            action=action,
            error=str(exc),
        )


def _save_checkpoint_safe(
    task_id,
    step,
    memory,
    resolved_mode,
):
    try:
        from storage.checkpoint_store import save_checkpoint
        from context.tms import export_mutation_state_for_checkpoint

        mutation_state = export_mutation_state_for_checkpoint()

        result = save_checkpoint(
            task_id,
            step,
            memory,
            resolved_mode,
            repo_root=str(REPO_ROOT),
            context_state=_export_context_state_for_checkpoint(),
            mutation_state=mutation_state,
            execution_state=None,
            mutation_fsm=None,
        )

        if result.ok:
            log_react_step(
                "checkpoint_saved",
                task_id=task_id,
                react_step=step,
                checkpoint_id=result.checkpoint_id,
                memory_bytes=result.memory_bytes,
            )
        elif result.skipped:
            log_react_step(
                "checkpoint_skipped",
                task_id=task_id,
                react_step=step,
                reason=result.reason,
                memory_bytes=result.memory_bytes,
            )
    except Exception as exc:
        log_react_step(
            "checkpoint_save_failed",
            task_id=task_id,
            react_step=step,
            error=str(exc),
        )


def _exit_on_cancel_requested(task_id, step, memory, resolved_mode):
    if not is_cancel_requested(task_id):
        return None

    _save_checkpoint_safe(
        task_id,
        step,
        memory,
        resolved_mode,
    )

    log_react_step(
        "task_cancelled",
        task_id=task_id,
        react_step=step,
        reason="user_request",
    )

    mark_task_cancelled(task_id)

    return DEFAULT_CANCEL_ANSWER, memory


# ---- Memory trimming helpers ----


def _estimate_memory_chars(memory):
    """Return the estimated total characters across all messages in *memory*."""
    total = 0
    for msg in memory:
        total += len(str(msg.get("content", "")))
    return total


# Lazy-loaded tiktoken encoder.
_token_encoder = None


def _get_token_encoder():
    global _token_encoder
    if _token_encoder is None:
        try:
            import tiktoken
            _token_encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            logger.warning("tiktoken 不可用，回退到字符估算")
            _token_encoder = False  # sentinel: unavailable
    return _token_encoder if _token_encoder is not False else None


def _estimate_memory_tokens(memory):
    """Return the estimated total tokens across all messages using tiktoken.

    Returns 0 when tiktoken is unavailable (caller should fall back to chars).
    """
    enc = _get_token_encoder()
    if enc is None:
        return 0
    total = 0
    for msg in memory:
        content = str(msg.get("content", ""))
        total += len(enc.encode(content))
    return total


def _trim_memory(memory):
    """Trim older messages from *memory* in-place to prevent context overflow.

    Strategy:
      - system messages are **always** preserved.
      - The most recent REACT_KEEP_RECENT_ROUNDS × 2 non-system messages are kept.
      - Older non-system messages are removed.

    Token-based trimming is used when REACT_MAX_CONTEXT_TOKENS > 0 and
    tiktoken is available; otherwise falls back to REACT_MAX_CONTEXT_CHARS.

    Skipped when both limits are 0.
    """
    if not memory:
        return

    # Determine active limit
    use_tokens = REACT_MAX_CONTEXT_TOKENS > 0
    limit = REACT_MAX_CONTEXT_TOKENS if use_tokens else REACT_MAX_CONTEXT_CHARS

    if limit == 0:
        return

    if use_tokens:
        total = _estimate_memory_tokens(memory)
        if total == 0:
            # tiktoken unavailable → fall back to chars
            limit = REACT_MAX_CONTEXT_CHARS
            if limit == 0:
                return
            total = _estimate_memory_chars(memory)
            use_tokens = False
    else:
        total = _estimate_memory_chars(memory)

    if total <= limit:
        return

    system_msgs = [m for m in memory if m.get("role") == "system"]
    non_system = [m for m in memory if m.get("role") != "system"]

    keep_count = REACT_KEEP_RECENT_ROUNDS * 2
    if keep_count >= len(non_system):
        return  # nothing to trim

    kept_non_system = non_system[-keep_count:]
    removed = len(non_system) - keep_count

    memory[:] = system_msgs + kept_non_system
    logger.info(
        "memory 已裁剪: 移除 %d 条非system消息, ~%d %s → %d 条 (system=%d)",
        removed,
        total,
        "tokens" if use_tokens else "chars",
        len(memory),
        len(system_msgs),
    )


def _init_session(task_id, agent_mode, max_steps, confirm_callback):
    """Initialize agent session parameters: task_id, mode, tokens.

    Returns a dict with all session-level values needed by react_agent().
    """
    owns_session = task_id is None

    if task_id is None:
        task_id = uuid.uuid4().hex[:8]

    resolved_mode = resolve_agent_mode(agent_mode)
    existing_task = get_task(task_id)

    if existing_task and existing_task.get("agent_mode"):
        resolved_mode = resolve_agent_mode(existing_task["agent_mode"])

    step_limit = max_steps if max_steps is not None else REACT_MAX_STEPS

    task_token = set_task_id(task_id)
    confirm_token = set_confirm_callback(confirm_callback)
    mode_token = set_agent_mode(resolved_mode)

    return {
        "task_id": task_id,
        "owns_session": owns_session,
        "resolved_mode": resolved_mode,
        "step_limit": step_limit,
        "task_token": task_token,
        "confirm_token": confirm_token,
        "mode_token": mode_token,
        "existing_task": existing_task,
    }


def _setup_memory(question, memory, task_id, resolved_mode, is_resume, *,
                  resume_from_step=None, initial_memory=None,
                  initial_context_state=None, initial_execution_state=None,
                  initial_mutation_fsm=None, initial_mutation_state=None,
                  existing_task=None):
    """Prepare memory and starting step for resume / new-task / follow-up.

    Returns (step, memory).
    """
    step = resume_from_step if is_resume else 0

    if is_resume:
        from context.budget_state import restore_context_budget_state
        from context.tms.resume import (
            build_tms_resume_hint,
            clear_tms_backup_milestones,
            user_requests_rebackup,
        )
        from context.tms import (
            apply_checkpoint_hydrate_safe_state,
            apply_checkpoint_mutation_state_to_runtime,
            hydrate_checkpoint_mutation_state,
        )

        restore_context_budget_state(initial_context_state)

        fsm_source = "reset"
        fsm_mismatch = False

        try:
            state, hydrate_diag = hydrate_checkpoint_mutation_state(
                mutation_state=initial_mutation_state,
                execution_state=initial_execution_state,
                mutation_fsm=initial_mutation_fsm,
                task_id=task_id,
            )
            if hydrate_diag.corrupted:
                apply_checkpoint_hydrate_safe_state(
                    task_id=task_id,
                    react_step=resume_from_step,
                    error="; ".join(hydrate_diag.warnings),
                )
                fsm_source = "safe_state"
            else:
                apply_checkpoint_mutation_state_to_runtime(
                    state,
                    task_id=task_id,
                    react_step=resume_from_step,
                )
                fsm_source = hydrate_diag.source
                fsm_mismatch = hydrate_diag.derive_mismatch
        except Exception as exc:
            log_react_step(
                "mutation_state_restore_failed",
                task_id=task_id,
                error=str(exc),
            )
            apply_checkpoint_hydrate_safe_state(
                task_id=task_id,
                react_step=resume_from_step,
                error=str(exc),
            )
            fsm_source = "safe_state"
            fsm_mismatch = False

        if initial_memory is not None:
            memory = list(initial_memory)
        elif memory is not None:
            memory = list(memory)
        else:
            memory = []

        log_react_step(
            "task_resumed",
            task_id=task_id,
            react_step=resume_from_step,
            agent_mode=resolved_mode,
        )

        try:
            from context.tms.context import get_shadow

            shadow = get_shadow()
            log_react_step(
                "mutation_state_restored",
                task_id=task_id,
                workflow_state=shadow.workflow.state.value,
                workflow_path=shadow.workflow.path.value,
                hydrate_source=fsm_source,
                derive_mismatch=fsm_mismatch,
                has_proposal_digest=bool(shadow.workflow.proposal_digest),
            )
        except Exception as e:
            logger.warning("mutation_state_restored 日志记录失败: %s", e, exc_info=True)

        hint = build_tms_resume_hint()
        if hint:
            memory.append({"role": "user", "content": hint})

        update_task(task_id, status=TASK_STATUS_RUNNING)

        follow_up = str(question or "").strip()
        if follow_up:
            if user_requests_rebackup(follow_up):
                clear_tms_backup_milestones()
            log_react_step("user_followup", task_id=task_id, question=follow_up)
            memory.append({"role": "user", "content": follow_up})

    elif memory is None:
        try:
            from context.tms import reset_mutation_state
            reset_mutation_state()
        except Exception as e:
            logger.warning("reset_mutation_state 失败: %s", e, exc_info=True)

        log_react_step(
            "task_start",
            task_id=task_id,
            question=question,
            agent_mode=resolved_mode,
        )

        if existing_task is None:
            create_task(
                task_id,
                question,
                repo_root=str(REPO_ROOT),
                status=TASK_STATUS_RUNNING,
                agent_mode=resolved_mode,
            )

        memory = [{"role": "user", "content": question}]

    else:
        try:
            from context.tms.resume import (
                clear_tms_backup_milestones,
                user_requests_rebackup,
            )
            if user_requests_rebackup(question):
                clear_tms_backup_milestones()
        except Exception as e:
            logger.warning("clear_tms_backup_milestones 失败: %s", e, exc_info=True)

        log_react_step("user_followup", task_id=task_id, question=question)
        memory.append({"role": "user", "content": question})

    return step, memory


def _run_react_loop(step, memory, task_id, resolved_mode, step_limit):
    """Execute the ReAct reasoning loop: AI → parse → execute → repeat.

    Returns (answer, memory) when the task completes or is cancelled.
    """
    while True:
        step += 1
        t_step_start = time.perf_counter()

        cancelled = _exit_on_cancel_requested(task_id, step, memory, resolved_mode)
        if cancelled is not None:
            return cancelled

        if step > step_limit:
            message = (
                "已达到最大 ReAct 步数 ("
                + str(step_limit)
                + ")，请简化任务或分步提问。"
            )
            _save_checkpoint_safe(task_id, step - 1, memory, resolved_mode)
            log_react_step(
                "max_steps_reached",
                task_id=task_id,
                steps=step_limit,
                limit=step_limit,
            )
            update_task(task_id, status=TASK_STATUS_FAILED, answer=message)
            return message, memory

        cancelled = _exit_on_cancel_requested(task_id, step, memory, resolved_mode)
        if cancelled is not None:
            return cancelled

        _trim_memory(memory)

        t_llm_start = time.perf_counter()
        response = ask_ai(memory, agent_mode=resolved_mode)
        t_llm_ms = (time.perf_counter() - t_llm_start) * 1000
        prompt_tokens, completion_tokens = get_last_token_usage()
        record_llm_call(t_llm_ms, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        log_react_step("ai_output", task_id=task_id, response=response)
        logger.info("LLM 调用耗时: %.0fms", t_llm_ms)

        print("\nAI输出:", response)
        logger.info("AI输出: %s", response[:500])

        parsed = parse_agent_response(response)

        if isinstance(parsed, str):
            log_react_step("plain_answer", task_id=task_id, answer=parsed)
            update_task(task_id, status=TASK_STATUS_COMPLETED, answer=parsed)
            return parsed, memory

        if isinstance(parsed, FinishResponse):
            log_react_step("finish", task_id=task_id, answer=parsed.answer)
            update_task(task_id, status=TASK_STATUS_COMPLETED, answer=parsed.answer)
            return parsed.answer, memory

        if isinstance(parsed, ToolCall):
            log_react_step(
                "tool_request",
                task_id=task_id,
                action=parsed.action,
                args=parsed.args,
            )

            if is_cancel_requested(task_id):
                cancelled = _exit_on_cancel_requested(
                    task_id, step, memory, resolved_mode,
                )
                if cancelled is not None:
                    return cancelled

            t_tool_start = time.perf_counter()
            result = run_tool(parsed.action, parsed.args)
            t_tool_ms = (time.perf_counter() - t_tool_start) * 1000
            record_tool_call(parsed.action, t_tool_ms)
            result_for_state = format_tool_result_for_display(result)

            _update_execution_state_safe(
                task_id,
                parsed.action,
                parsed.args,
                result_for_state,
            )

            log_react_step(
                "tool_result",
                task_id=task_id,
                action=parsed.action,
                result=result_for_state,
            )

            print("\n工具返回:", result_for_state)
            logger.info("工具返回(action=%s): %s", parsed.action, str(result_for_state)[:200])
            logger.info("工具耗时(action=%s): %.0fms", parsed.action, t_tool_ms)

            memory.append({"role": "assistant", "content": response})
            memory.append({
                "role": "user",
                "content": "工具执行结果:\n" + format_tool_result_for_memory(result),
            })

            _save_checkpoint_safe(task_id, step, memory, resolved_mode)

        t_step_ms = (time.perf_counter() - t_step_start) * 1000
        record_agent_step_duration(t_step_ms)
        logger.info("ReAct step %d 耗时: %.0fms", step, t_step_ms)


def react_agent(
    question,
    memory=None,
    task_id=None,
    confirm_callback=None,
    max_steps=None,
    agent_mode=None,
    *,
    resume_from_step=None,
    initial_memory=None,
    initial_context_state=None,
    initial_execution_state=None,
    initial_mutation_fsm=None,
    initial_mutation_state=None,
):
    """Public ReAct agent entry-point — delegates to session/memory/loop helpers."""
    is_resume = resume_from_step is not None

    sess = _init_session(task_id, agent_mode, max_steps, confirm_callback)
    task_id = sess["task_id"]
    resolved_mode = sess["resolved_mode"]
    step_limit = sess["step_limit"]
    owns_session = sess["owns_session"]

    step, memory = _setup_memory(
        question, memory,
        task_id, resolved_mode, is_resume,
        resume_from_step=resume_from_step,
        initial_memory=initial_memory,
        initial_context_state=initial_context_state,
        initial_execution_state=initial_execution_state,
        initial_mutation_fsm=initial_mutation_fsm,
        initial_mutation_state=initial_mutation_state,
        existing_task=sess["existing_task"],
    )

    try:
        return _run_react_loop(step, memory, task_id, resolved_mode, step_limit)
    finally:
        reset_agent_mode(sess["mode_token"])
        if owns_session:
            reset_confirm_callback(sess["confirm_token"])
            reset_task_id(sess["task_token"])




def run_react_cli(confirm_callback=None):

    cli_mode = resolve_agent_mode(None)

    print(
        "Agent 会话已启动（模式: "
        + cli_mode
        + "，输入 exit 退出）"
    )
    logger.info("Agent 会话已启动（模式: %s）", cli_mode)

    memory = None

    session_task_id = uuid.uuid4().hex[:8]

    task_token = set_task_id(session_task_id)

    confirm_token = set_confirm_callback(confirm_callback)

    mode_token = set_agent_mode(cli_mode)


    try:


        while True:


            question = input("\n请输入: ").strip()


            if not question:

                continue


            if question.lower() in ("exit", "quit", "q"):

                break


            answer, memory = react_agent(

                question,

                memory=memory,

                task_id=session_task_id,

                confirm_callback=confirm_callback,

                agent_mode=cli_mode,

            )


            print("\n回答:", answer)
            logger.info("回答(task=%s): %s", session_task_id, str(answer)[:200])


    finally:

        reset_agent_mode(mode_token)

        reset_confirm_callback(confirm_token)

        reset_task_id(task_token)




if __name__ == "__main__":

    run_react_cli()
