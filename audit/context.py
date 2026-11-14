from contextvars import ContextVar


current_task_id: ContextVar[str | None] = ContextVar(
    "current_task_id",
    default=None,
)

confirm_callback_var: ContextVar = ContextVar(
    "confirm_callback",
    default=None,
)

skip_tool_confirm_var: ContextVar[bool] = ContextVar(
    "skip_tool_confirm",
    default=False,
)

stream_event_callback_var: ContextVar = ContextVar(
    "stream_event_callback",
    default=None,
)

agent_mode_var: ContextVar[str | None] = ContextVar(
    "agent_mode",
    default=None,
)



def set_task_id(task_id: str):

    return current_task_id.set(task_id)


def get_task_id():

    return current_task_id.get()


def reset_task_id(token):

    current_task_id.reset(token)



def set_confirm_callback(callback):

    return confirm_callback_var.set(callback)


def get_confirm_callback():

    return confirm_callback_var.get()


def reset_confirm_callback(token):

    confirm_callback_var.reset(token)


def set_skip_tool_confirm(skip=True):

    return skip_tool_confirm_var.set(skip)


def is_tool_confirm_skipped():

    return skip_tool_confirm_var.get()


def reset_skip_tool_confirm(token):

    skip_tool_confirm_var.reset(token)



def set_stream_event_callback(callback):

    return stream_event_callback_var.set(callback)


def get_stream_event_callback():

    return stream_event_callback_var.get()


def reset_stream_event_callback(token):

    stream_event_callback_var.reset(token)


def publish_stream_event(record):

    callback = stream_event_callback_var.get()


    if callback is not None:

        callback(record)



def set_agent_mode(mode):

    return agent_mode_var.set(mode)



def get_agent_mode():

    return agent_mode_var.get()



def reset_agent_mode(token):

    agent_mode_var.reset(token)
