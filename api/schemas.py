from pydantic import BaseModel, Field, field_validator

from config.agent_mode import AGENT_MODE_FULL, parse_agent_mode


class HealthResponse(BaseModel):

    status: str

    version: str

    service: str = "RepoPilot"

    agent_mode: str = Field(
        description="Default AGENT_MODE from environment (full or readonly)",
    )



class TaskResponse(BaseModel):

    task_id: str

    status: str

    question: str

    answer: str | None = None

    repo_root: str

    agent_mode: str = AGENT_MODE_FULL

    created_at: str

    updated_at: str



class TaskListResponse(BaseModel):

    tasks: list[TaskResponse]

    count: int

    limit: int = Field(description="Applied list limit")



class ErrorResponse(BaseModel):

    detail: str



class TaskCreateRequest(BaseModel):

    question: str = Field(
        min_length=1,
        max_length=10000,
        description="User question or task for the agent",
    )

    mode: str | None = Field(
        default=None,
        description="Agent mode override: readonly or full (default from AGENT_MODE env)",
    )

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value):

        if value is None:

            return None


        return parse_agent_mode(value)



class TaskCreateResponse(BaseModel):

    task_id: str

    status: str

    agent_mode: str = AGENT_MODE_FULL

    message: str = "Agent task accepted and running in background"



class TaskReportResponse(BaseModel):

    task_id: str

    report: str



class TaskConfirmRequest(BaseModel):

    confirmed: bool = Field(
        description="true to approve pending tool execution, false to reject",
    )



class TaskConfirmResponse(BaseModel):

    task_id: str

    accepted: bool

    confirmed: bool

    message: str



class PendingConfirmResponse(BaseModel):

    task_id: str

    pending: bool

    tool: str | None = None

    args: dict | None = None



class TaskCancelResponse(BaseModel):

    task_id: str

    status: str

    cancel_requested: bool

    result: str = Field(description="success when cancel flag was set")



class TaskResumeRequest(BaseModel):

    question: str = Field(
        default="",
        max_length=10000,
        description="Optional follow-up; empty continues from checkpoint",
    )



class TaskResumeResponse(BaseModel):

    task_id: str

    status: str

    resumed_from_step: int

    checkpoint_id: str

    message: str = "Agent task resumed in background"
