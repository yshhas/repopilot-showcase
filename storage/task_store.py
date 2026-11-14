import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from config.agent_mode import AGENT_MODE_FULL, parse_agent_mode
from config.settings import REPO_ROOT, TASK_DB_FILE


TASK_STATUS_RUNNING = "running"

TASK_STATUS_COMPLETED = "completed"

TASK_STATUS_FAILED = "failed"

TASK_STATUS_CANCELLED = "cancelled"

DEFAULT_CANCEL_ANSWER = "任务已取消"


@dataclass(frozen=True)
class CancelRequestResult:
    ok: bool
    reason: str | None = None



def _utc_now():

    return datetime.now(timezone.utc).isoformat()



def _connect():

    TASK_DB_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    conn = sqlite3.connect(str(TASK_DB_FILE))

    conn.row_factory = sqlite3.Row

    return conn



def _ensure_agent_mode_column(conn):

    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
    }


    if "agent_mode" not in columns:

        conn.execute(
            "ALTER TABLE tasks ADD COLUMN agent_mode TEXT NOT NULL DEFAULT 'full'"
        )



def _ensure_cancel_requested_column(conn):

    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
    }


    if "cancel_requested" not in columns:

        conn.execute(
            "ALTER TABLE tasks ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0"
        )



def _normalize_task_record(record):

    if record.get("agent_mode") is None:

        record["agent_mode"] = AGENT_MODE_FULL


    if "cancel_requested" not in record or record["cancel_requested"] is None:

        record["cancel_requested"] = 0

    else:

        record["cancel_requested"] = int(record["cancel_requested"])


    return record



def init_task_db():

    with _connect() as conn:

        conn.execute(

            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT,
                repo_root TEXT NOT NULL,
                agent_mode TEXT NOT NULL DEFAULT 'full',
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        _ensure_agent_mode_column(conn)

        _ensure_cancel_requested_column(conn)

        conn.commit()



def create_task(
    task_id,
    question,
    repo_root=None,
    status=TASK_STATUS_RUNNING,
    agent_mode=AGENT_MODE_FULL,
):

    init_task_db()

    now = _utc_now()

    repo = str(repo_root or REPO_ROOT)

    mode = parse_agent_mode(agent_mode)


    with _connect() as conn:

        conn.execute(

            """
            INSERT INTO tasks (
                task_id,
                status,
                question,
                answer,
                repo_root,
                agent_mode,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,

            (
                task_id,
                status,
                question,
                None,
                repo,
                mode,
                now,
                now,
            ),

        )

        conn.commit()



def update_task(
    task_id,
    status=None,
    answer=None,
):

    init_task_db()

    fields = []

    values = []


    if status is not None:

        fields.append("status = ?")

        values.append(status)


    if answer is not None:

        fields.append("answer = ?")

        values.append(answer)


    if not fields:

        return


    fields.append("updated_at = ?")

    values.append(_utc_now())

    values.append(task_id)


    with _connect() as conn:

        conn.execute(

            "UPDATE tasks SET "
            + ", ".join(fields)
            + " WHERE task_id = ?",

            values,

        )

        conn.commit()



def get_task(task_id):

    init_task_db()


    with _connect() as conn:

        row = conn.execute(

            "SELECT * FROM tasks WHERE task_id = ?",

            (task_id,),

        ).fetchone()


    if row is None:

        return None


    record = dict(row)

    return _normalize_task_record(record)



def request_cancel(task_id):

    init_task_db()

    task = get_task(task_id)


    if task is None:

        return CancelRequestResult(
            ok=False,
            reason="not_found",
        )


    if task["status"] == TASK_STATUS_CANCELLED:

        return CancelRequestResult(
            ok=False,
            reason="already_cancelled",
        )


    if task["status"] != TASK_STATUS_RUNNING:

        return CancelRequestResult(
            ok=False,
            reason="not_running",
        )


    if int(task.get("cancel_requested", 0)):

        return CancelRequestResult(
            ok=False,
            reason="already_requested",
        )


    with _connect() as conn:

        conn.execute(

            """
            UPDATE tasks
            SET cancel_requested = 1, updated_at = ?
            WHERE task_id = ?
            """,

            (
                _utc_now(),
                task_id,
            ),

        )

        conn.commit()


    return CancelRequestResult(
        ok=True,
        reason=None,
    )



def is_cancel_requested(task_id):

    task = get_task(task_id)


    if task is None:

        return False


    return bool(int(task.get("cancel_requested", 0)))



def clear_cancel_request(task_id):

    init_task_db()


    with _connect() as conn:

        cursor = conn.execute(

            """
            UPDATE tasks
            SET cancel_requested = 0, updated_at = ?
            WHERE task_id = ?
            """,

            (
                _utc_now(),
                task_id,
            ),

        )

        conn.commit()

        updated = cursor.rowcount


    return updated > 0



def mark_task_cancelled(
    task_id,
    answer=None,
):

    init_task_db()

    message = DEFAULT_CANCEL_ANSWER if answer is None else answer


    with _connect() as conn:

        conn.execute(

            """
            UPDATE tasks
            SET status = ?, answer = ?, cancel_requested = 0, updated_at = ?
            WHERE task_id = ?
            """,

            (
                TASK_STATUS_CANCELLED,
                message,
                _utc_now(),
                task_id,
            ),

        )

        conn.commit()



def list_tasks(limit=20):

    init_task_db()


    with _connect() as conn:

        rows = conn.execute(

            """
            SELECT * FROM tasks
            ORDER BY created_at DESC
            LIMIT ?
            """,

            (limit,),

        ).fetchall()


    results = []


    for row in rows:

        record = dict(row)

        results.append(_normalize_task_record(record))


    return results
