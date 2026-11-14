import logging

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from api.auth import register_api_key_middleware
from api.agent_runner import schedule_agent_task, schedule_resume_task
from api.deps import clamp_list_limit, fetch_task, fetch_tasks
from api.schemas import (
    HealthResponse,
    PendingConfirmResponse,
    TaskConfirmRequest,
    TaskConfirmResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskCancelResponse,
    TaskListResponse,
    TaskReportResponse,
    TaskResumeRequest,
    TaskResumeResponse,
    TaskResponse,
)
from api.task_confirm import get_pending_confirmation, submit_confirmation
from api.task_stream import iter_task_events
from audit.audit_log import log_react_step
from audit.task_report import generate_task_report
from config.agent_mode import resolve_agent_mode
from config.settings import APP_VERSION, API_DEFAULT_LIST_LIMIT
from storage.task_store import TASK_STATUS_RUNNING, request_cancel

logger = logging.getLogger(__name__)


app = FastAPI(

    title="RepoPilot API",

    version=APP_VERSION,

    description=(
        "Enterprise dev agent HTTP API "
        "(C3–C7: tasks, SSE, report, confirm, agent mode)"
    ),

)


register_api_key_middleware(app)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate Limiting
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Max request body size: 1 MB
_MAX_BODY_SIZE = 1_000_000


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > _MAX_BODY_SIZE:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=413,
            content={"detail": "Request body exceeds 1 MB limit"},
        )
    return await call_next(request)


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["system"],
)
def health_check():
    return HealthResponse(
        status="ok",
        version=APP_VERSION,
        service="RepoPilot",
        agent_mode=resolve_agent_mode(None),
    )


@app.get(
    "/metrics",
    tags=["system"],
)
def metrics_endpoint():
    """Return in-process observability metrics (JSON).

    Tracks: agent step count/duration, LLM call count/duration/tokens,
    tool call count/duration by tool name, task lifecycle counts.
    """
    try:
        from observability import snapshot
        return snapshot()
    except ImportError:
        return {"error": "observability module not available"}



@app.get(
    "/tasks",
    response_model=TaskListResponse,
    tags=["tasks"],
)
def list_tasks_endpoint(

    limit: int = Query(
        default=API_DEFAULT_LIST_LIMIT,
        ge=1,
        le=100,
        description="Maximum number of tasks to return",
    ),

):

    applied = clamp_list_limit(limit)

    rows = fetch_tasks(limit=applied)

    tasks = [TaskResponse.model_validate(row) for row in rows]


    return TaskListResponse(

        tasks=tasks,

        count=len(tasks),

        limit=applied,

    )



@app.post(
    "/tasks",
    response_model=TaskCreateResponse,
    status_code=201,
    tags=["tasks"],
)
@limiter.limit("10/minute")
def create_task_endpoint(body: TaskCreateRequest, request: Request):

    question = body.question.strip()


    if not question:

        raise HTTPException(
            status_code=422,
            detail="question must not be empty",
        )


    task_id = schedule_agent_task(
        question,
        agent_mode=body.mode,
    )

    resolved_mode = resolve_agent_mode(body.mode)


    return TaskCreateResponse(
        task_id=task_id,
        status=TASK_STATUS_RUNNING,
        agent_mode=resolved_mode,
    )



@app.get(
    "/tasks/{task_id}",
    response_model=TaskResponse,
    responses={404: {"description": "Task not found"}},
    tags=["tasks"],
)
def get_task_endpoint(task_id: str):

    row = fetch_task(task_id)


    if row is None:

        raise HTTPException(
            status_code=404,
            detail="Task not found: " + task_id,
        )


    return TaskResponse.model_validate(row    )



@app.post(
    "/tasks/{task_id}/cancel",
    response_model=TaskCancelResponse,
    responses={
        404: {"description": "Task not found"},
        409: {"description": "Cancel not allowed"},
    },
    tags=["tasks"],
)
def cancel_task_endpoint(task_id: str):

    row = fetch_task(task_id)


    if row is None:

        raise HTTPException(
            status_code=404,
            detail="not_found",
        )


    result = request_cancel(task_id)


    if not result.ok:

        if result.reason == "not_found":

            raise HTTPException(
                status_code=404,
                detail="not_found",
            )


        raise HTTPException(
            status_code=409,
            detail=result.reason or "cancel_failed",
        )


    cancel_step = None

    try:

        from storage.checkpoint_store import get_latest_checkpoint

        checkpoint = get_latest_checkpoint(task_id)

        if checkpoint is not None:

            cancel_step = checkpoint.step

    except Exception as e:
        logger.warning("cancel 端点获取 checkpoint 失败(task=%s): %s", task_id, e, exc_info=True)
        cancel_step = None


    log_react_step(
        "cancel_requested",
        task_id=task_id,
        reason="user_request",
        react_step=cancel_step,
    )


    task = fetch_task(task_id)


    return TaskCancelResponse(
        task_id=task_id,
        status=task["status"],
        cancel_requested=True,
        result="success",
    )



@app.post(
    "/tasks/{task_id}/resume",
    response_model=TaskResumeResponse,
    status_code=200,
    responses={
        404: {"description": "Task or checkpoint not found"},
        409: {"description": "Resume not allowed"},
    },
    tags=["tasks"],
)
def resume_task_endpoint(task_id: str, body: TaskResumeRequest):

    row = fetch_task(task_id)


    if row is None:

        raise HTTPException(
            status_code=404,
            detail="not_found",
        )


    result = schedule_resume_task(
        task_id,
        question=body.question,
    )


    if not result.ok:

        if result.reason == "not_found":

            raise HTTPException(
                status_code=404,
                detail="not_found",
            )


        if result.reason == "no_checkpoint":

            raise HTTPException(
                status_code=404,
                detail="no_checkpoint",
            )


        raise HTTPException(
            status_code=409,
            detail=result.reason or "resume_failed",
        )


    return TaskResumeResponse(
        task_id=task_id,
        status=TASK_STATUS_RUNNING,
        resumed_from_step=result.resumed_from_step,
        checkpoint_id=result.checkpoint_id,
    )



@app.get(
    "/tasks/{task_id}/report",
    response_model=TaskReportResponse,
    responses={404: {"description": "Task not found"}},
    tags=["tasks"],
)
def get_task_report_endpoint(task_id: str):

    row = fetch_task(task_id)


    if row is None:

        raise HTTPException(
            status_code=404,
            detail="Task not found: " + task_id,
        )


    report = generate_task_report(task_id)


    return TaskReportResponse(
        task_id=task_id,
        report=report,
    )



@app.get(
    "/tasks/{task_id}/confirm/pending",
    response_model=PendingConfirmResponse,
    responses={404: {"description": "Task not found"}},
    tags=["tasks"],
)
def get_pending_confirm_endpoint(task_id: str):

    row = fetch_task(task_id)


    if row is None:

        raise HTTPException(
            status_code=404,
            detail="Task not found: " + task_id,
        )


    pending = get_pending_confirmation(task_id)


    if pending is None:

        return PendingConfirmResponse(
            task_id=task_id,
            pending=False,
        )


    return PendingConfirmResponse(
        task_id=task_id,
        pending=True,
        tool=pending["tool"],
        args=pending["args"],
    )



@app.post(
    "/tasks/{task_id}/confirm",
    response_model=TaskConfirmResponse,
    responses={
        404: {"description": "Task not found"},
        409: {"description": "No pending confirmation"},
    },
    tags=["tasks"],
)
def confirm_task_endpoint(
    task_id: str,
    body: TaskConfirmRequest,
):

    row = fetch_task(task_id)


    if row is None:

        raise HTTPException(
            status_code=404,
            detail="Task not found: " + task_id,
        )


    if not submit_confirmation(task_id, body.confirmed):

        raise HTTPException(
            status_code=409,
            detail="No pending confirmation for task: " + task_id,
        )


    message = (
        "Tool execution approved"
        if body.confirmed
        else "Tool execution rejected"
    )


    return TaskConfirmResponse(
        task_id=task_id,
        accepted=True,
        confirmed=body.confirmed,
        message=message,
    )



@app.get(
    "/tasks/{task_id}/stream",
    tags=["tasks"],
    responses={404: {"description": "Task not found"}},
)
async def stream_task_endpoint(task_id: str):

    row = fetch_task(task_id)


    if row is None:

        raise HTTPException(
            status_code=404,
            detail="Task not found: " + task_id,
        )


    return StreamingResponse(
        iter_task_events(task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )



if __name__ == "__main__":

    import uvicorn


    uvicorn.run(
        "api.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
