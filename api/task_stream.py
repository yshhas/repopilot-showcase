import asyncio
import json
import queue
import threading

from audit.task_report import load_events_for_task
from storage.task_store import TASK_STATUS_RUNNING, get_task


SSE_QUEUE_TIMEOUT = 15.0

_task_queues: dict[str, queue.Queue] = {}

_queues_lock = threading.Lock()



def _event_key(event):

    return (
        event.get("time"),
        event.get("event"),
        event.get("step"),
        event.get("tool"),
    )



def format_sse(event):

    payload = json.dumps(
        event,
        ensure_ascii=False,
    )

    return "data: " + payload + "\n\n"



def ensure_task_queue(task_id):

    with _queues_lock:

        if task_id not in _task_queues:

            _task_queues[task_id] = queue.Queue()


        return _task_queues[task_id]



def get_task_queue(task_id):

    with _queues_lock:

        return _task_queues.get(task_id)



def publish_to_task_queue(task_id, event):

    with _queues_lock:

        task_queue = _task_queues.get(task_id)


    if task_queue is not None:

        task_queue.put(event)



def remove_task_queue(task_id):

    with _queues_lock:

        _task_queues.pop(task_id, None)



def make_stream_callback(task_id):

    def callback(record):

        if record.get("task_id") == task_id:

            publish_to_task_queue(task_id, record)


    return callback



async def iter_task_events(task_id):

    seen = set()


    for event in load_events_for_task(task_id):

        key = _event_key(event)


        if key in seen:

            continue


        seen.add(key)

        yield format_sse(event)


    task = get_task(task_id)


    if task and task["status"] == TASK_STATUS_RUNNING:

        task_queue = get_task_queue(task_id)


        if task_queue is not None:

            while True:

                try:

                    event = await asyncio.to_thread(
                        task_queue.get,
                        True,
                        SSE_QUEUE_TIMEOUT,
                    )

                except queue.Empty:

                    task = get_task(task_id)


                    if not task or task["status"] != TASK_STATUS_RUNNING:

                        break


                    yield ": heartbeat\n\n"

                    continue


                key = _event_key(event)


                if key not in seen:

                    seen.add(key)

                    yield format_sse(event)


                if event.get("event") == "stream_end":

                    return


        task = get_task(task_id)


    yield format_sse({

        "event": "stream_end",

        "task_id": task_id,

        "status": task.get("status") if task else "unknown",

    })
