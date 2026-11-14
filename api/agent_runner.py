import threading
import uuid
from dataclasses import dataclass

from audit.audit_log import log_react_step
from audit.context import reset_stream_event_callback, set_stream_event_callback
from api.task_confirm import clear_pending_confirmation, make_api_confirm_callback
from api.task_stream import (
    ensure_task_queue,
    make_stream_callback,
    publish_to_task_queue,
    remove_task_queue,
)
from config.agent_mode import resolve_agent_mode
import config.settings as app_settings
from react_agent import react_agent
from storage.checkpoint_store import get_latest_checkpoint
from storage.task_store import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_FAILED,
    TASK_STATUS_RUNNING,
    create_task,
    get_task,
    update_task,
)


@dataclass(frozen=True)
class ResumeTaskResult:
    ok: bool
    reason: str | None = None
    resumed_from_step: int | None = None
    checkpoint_id: str | None = None


def run_agent_task(
    question,
    task_id,
    agent_mode=None,
    confirm_callback=None,
    *,
    resume_from_step=None,
    initial_memory=None,
    initial_context_state=None,
    initial_execution_state=None,
    initial_mutation_fsm=None,
    initial_mutation_state=None,
):

    callback = confirm_callback or make_api_confirm_callback(task_id)

    resolved_mode = resolve_agent_mode(agent_mode)

    stream_token = set_stream_event_callback(
        make_stream_callback(task_id),
    )


    try:

        react_agent(
            question,
            task_id=task_id,
            confirm_callback=callback,
            agent_mode=resolved_mode,
            resume_from_step=resume_from_step,
            initial_memory=initial_memory,
            initial_context_state=initial_context_state,
            initial_execution_state=initial_execution_state,
            initial_mutation_fsm=initial_mutation_fsm,
            initial_mutation_state=initial_mutation_state,
        )


    except Exception as exc:

        if get_task(task_id) is not None:

            update_task(
                task_id,
                status=TASK_STATUS_FAILED,
                answer="Agent 执行异常: " + str(exc),
            )


    finally:

        reset_stream_event_callback(stream_token)

        task = get_task(task_id)

        publish_to_task_queue(
            task_id,
            {
                "event": "stream_end",
                "task_id": task_id,
                "status": task.get("status") if task else "unknown",
            },
        )

        remove_task_queue(task_id)



def schedule_agent_task(
    question,
    agent_mode=None,
    confirm_callback=None,
):

    task_id = uuid.uuid4().hex[:8]

    resolved_mode = resolve_agent_mode(agent_mode)

    ensure_task_queue(task_id)


    create_task(
        task_id,
        question,
        repo_root=str(app_settings.REPO_ROOT),
        status=TASK_STATUS_RUNNING,
        agent_mode=resolved_mode,
    )


    thread = threading.Thread(
        target=run_agent_task,
        args=(question, task_id),
        kwargs={
            "agent_mode": resolved_mode,
            "confirm_callback": confirm_callback,
        },
        name="agent-task-" + task_id,
        daemon=True,
    )

    thread.start()


    return task_id



def schedule_resume_task(task_id, question=""):

    task = get_task(task_id)


    if task is None:

        return ResumeTaskResult(
            ok=False,
            reason="not_found",
        )


    if task["status"] == TASK_STATUS_RUNNING:

        return ResumeTaskResult(
            ok=False,
            reason="already_running",
        )


    if task["status"] not in (
        TASK_STATUS_CANCELLED,
        TASK_STATUS_FAILED,
    ):

        return ResumeTaskResult(
            ok=False,
            reason="not_resumable",
        )


    checkpoint = get_latest_checkpoint(task_id)


    if checkpoint is None:

        return ResumeTaskResult(
            ok=False,
            reason="no_checkpoint",
        )


    if str(checkpoint.repo_root) != str(app_settings.REPO_ROOT):

        return ResumeTaskResult(
            ok=False,
            reason="repo_root_mismatch",
        )


    if clear_pending_confirmation(task_id):

        log_react_step(
            "confirm_cleared_on_resume",
            task_id=task_id,
        )


    ensure_task_queue(task_id)

    update_task(
        task_id,
        status=TASK_STATUS_RUNNING,
    )

    resolved_mode = resolve_agent_mode(checkpoint.agent_mode)


    thread = threading.Thread(
        target=run_agent_task,
        args=(question, task_id),
        kwargs={
            "agent_mode": resolved_mode,
            "resume_from_step": checkpoint.step,
            "initial_memory": checkpoint.memory,
            "initial_context_state": checkpoint.context_state,
            "initial_execution_state": checkpoint.execution_state,
            "initial_mutation_fsm": checkpoint.mutation_fsm,
            "initial_mutation_state": checkpoint.mutation_state,
        },
        name="agent-resume-" + task_id,
        daemon=True,
    )

    thread.start()


    return ResumeTaskResult(
        ok=True,
        resumed_from_step=checkpoint.step,
        checkpoint_id=checkpoint.checkpoint_id,
    )
