import threading

from api.task_stream import publish_to_task_queue
from config.settings import (
    API_CONFIRM_TIMEOUT_SECONDS,
    CONFIRM_REQUIRED_TOOLS,
)


_pending_lock = threading.Lock()

_pending: dict[str, dict] = {}



def make_api_confirm_callback(task_id):

    def callback(action, display_args):

        if action not in CONFIRM_REQUIRED_TOOLS:

            return True


        event = threading.Event()


        with _pending_lock:

            _pending[task_id] = {
                "tool": action,
                "args": display_args,
                "event": event,
                "confirmed": None,
            }


        publish_to_task_queue(
            task_id,
            {
                "event": "confirmation_required",
                "task_id": task_id,
                "tool": action,
                "args": display_args,
            },
        )


        if not event.wait(API_CONFIRM_TIMEOUT_SECONDS):

            with _pending_lock:

                _pending.pop(task_id, None)


            return False


        with _pending_lock:

            entry = _pending.pop(task_id, None)


        if entry is None:

            return False


        return bool(entry.get("confirmed"))


    return callback



def get_pending_confirmation(task_id):

    with _pending_lock:

        entry = _pending.get(task_id)


    if entry is None:

        return None


    return {
        "tool": entry["tool"],
        "args": entry["args"],
    }



def clear_pending_confirmation(task_id):

    with _pending_lock:

        entry = _pending.pop(task_id, None)


    if entry is None:

        return False


    entry["confirmed"] = False

    entry["event"].set()


    return True



def submit_confirmation(task_id, confirmed):

    with _pending_lock:

        entry = _pending.get(task_id)


    if entry is None:

        return False


    entry["confirmed"] = confirmed

    entry["event"].set()


    return True
