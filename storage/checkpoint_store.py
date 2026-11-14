"""SQLite persistence for ReAct task checkpoints (v0.6 C3-a)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from audit.logger import get_logger
from config import settings as app_settings
from config.agent_mode import parse_agent_mode
from config.settings import REPO_ROOT, TASK_DB_FILE

logger = get_logger("repopilot.checkpoint")


@dataclass(frozen=True)
class CheckpointRecord:
    checkpoint_id: str
    task_id: str
    step: int
    memory: list[dict[str, Any]]
    agent_mode: str
    repo_root: str
    context_state: dict[str, Any] | None
    mutation_state: dict[str, Any] | None
    execution_state: dict[str, Any] | None
    mutation_fsm: dict[str, Any] | None
    created_at: str


@dataclass(frozen=True)
class SaveCheckpointResult:
    ok: bool
    skipped: bool
    checkpoint_id: str | None
    reason: str | None
    memory_bytes: int | None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    TASK_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(TASK_DB_FILE))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_checkpoint_schema(conn: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(task_checkpoints)").fetchall()
    }
    if "mutation_fsm_json" not in columns:
        conn.execute(
            "ALTER TABLE task_checkpoints ADD COLUMN mutation_fsm_json TEXT"
        )
    if "mutation_state_json" not in columns:
        conn.execute(
            "ALTER TABLE task_checkpoints ADD COLUMN mutation_state_json TEXT"
        )


def init_checkpoint_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_checkpoints (
                checkpoint_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                step INTEGER NOT NULL,
                memory_json TEXT NOT NULL,
                agent_mode TEXT NOT NULL,
                repo_root TEXT NOT NULL,
                context_state_json TEXT,
                execution_state_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(task_id)
            )
            """
        )
        _ensure_checkpoint_schema(conn)
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_checkpoints_task
            ON task_checkpoints(task_id, step DESC)
            """
        )
        conn.commit()


def _serialize_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _deserialize_json(raw: str | None) -> Any | None:
    if raw is None or str(raw).strip() == "":
        return None
    return json.loads(raw)


def _row_to_record(row: sqlite3.Row) -> CheckpointRecord:
    memory = _deserialize_json(row["memory_json"])
    if not isinstance(memory, list):
        raise ValueError("checkpoint memory_json must decode to a list")

    context_state = _deserialize_json(row["context_state_json"])
    if context_state is not None and not isinstance(context_state, dict):
        raise ValueError("checkpoint context_state_json must decode to a dict")

    execution_state = _deserialize_json(row["execution_state_json"])
    if execution_state is not None and not isinstance(execution_state, dict):
        raise ValueError("checkpoint execution_state_json must decode to a dict")

    mutation_fsm = None
    if "mutation_fsm_json" in row.keys():
        mutation_fsm = _deserialize_json(row["mutation_fsm_json"])
        if mutation_fsm is not None and not isinstance(mutation_fsm, dict):
            raise ValueError("checkpoint mutation_fsm_json must decode to a dict")

    mutation_state = None
    if "mutation_state_json" in row.keys():
        mutation_state = _deserialize_json(row["mutation_state_json"])
        if mutation_state is not None and not isinstance(mutation_state, dict):
            raise ValueError("checkpoint mutation_state_json must decode to a dict")

    return CheckpointRecord(
        checkpoint_id=row["checkpoint_id"],
        task_id=row["task_id"],
        step=int(row["step"]),
        memory=memory,
        agent_mode=row["agent_mode"],
        repo_root=row["repo_root"],
        context_state=context_state,
        mutation_state=mutation_state,
        execution_state=execution_state,
        mutation_fsm=mutation_fsm,
        created_at=row["created_at"],
    )


def _prune_checkpoints(conn: sqlite3.Connection, task_id: str) -> int:
    rows = conn.execute(
        """
        SELECT checkpoint_id
        FROM task_checkpoints
        WHERE task_id = ?
        ORDER BY step DESC, created_at DESC
        """,
        (task_id,),
    ).fetchall()

    max_per_task = app_settings.CHECKPOINT_MAX_PER_TASK
    if len(rows) <= max_per_task:
        return 0

    stale_ids = [row["checkpoint_id"] for row in rows[max_per_task:]]
    conn.executemany(
        "DELETE FROM task_checkpoints WHERE checkpoint_id = ?",
        [(checkpoint_id,) for checkpoint_id in stale_ids],
    )
    return len(stale_ids)


def save_checkpoint(
    task_id: str,
    step: int,
    memory: list[dict[str, Any]],
    agent_mode: str,
    repo_root: str | None = None,
    *,
    context_state: dict[str, Any] | None = None,
    mutation_state: dict[str, Any] | None = None,
    execution_state: dict[str, Any] | None = None,
    mutation_fsm: dict[str, Any] | None = None,
) -> SaveCheckpointResult:
    if not app_settings.CHECKPOINT_ENABLED:
        return SaveCheckpointResult(
            ok=False,
            skipped=True,
            checkpoint_id=None,
            reason="disabled",
            memory_bytes=None,
        )

    memory_json = _serialize_json(memory)
    if memory_json is None:
        memory_json = "[]"

    memory_bytes = len(memory_json.encode("utf-8"))
    if memory_bytes > app_settings.CHECKPOINT_MAX_MEMORY_BYTES:
        logger.warning(
            "checkpoint save skipped: memory exceeds limit",
            extra={
                "extra_fields": {
                    "task_id": task_id,
                    "step": step,
                    "memory_bytes": memory_bytes,
                    "limit_bytes": app_settings.CHECKPOINT_MAX_MEMORY_BYTES,
                    "reason": "memory_too_large",
                }
            },
        )
        return SaveCheckpointResult(
            ok=False,
            skipped=True,
            checkpoint_id=None,
            reason="memory_too_large",
            memory_bytes=memory_bytes,
        )

    init_checkpoint_db()

    checkpoint_id = uuid.uuid4().hex
    created_at = _utc_now()
    mode = parse_agent_mode(agent_mode)
    repo = str(repo_root or REPO_ROOT)

    # PR-M5-e: v2 blob is authoritative; never dual-write v1 columns when present.
    if mutation_state is not None:
        execution_state = None
        mutation_fsm = None

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO task_checkpoints (
                checkpoint_id,
                task_id,
                step,
                memory_json,
                agent_mode,
                repo_root,
                context_state_json,
                mutation_state_json,
                execution_state_json,
                mutation_fsm_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                checkpoint_id,
                task_id,
                int(step),
                memory_json,
                mode,
                repo,
                _serialize_json(context_state),
                _serialize_json(mutation_state),
                _serialize_json(execution_state),
                _serialize_json(mutation_fsm),
                created_at,
            ),
        )
        pruned = _prune_checkpoints(conn, task_id)
        conn.commit()

    if pruned:
        logger.info(
            "checkpoint prune completed",
            extra={
                "extra_fields": {
                    "task_id": task_id,
                    "pruned_count": pruned,
                    "max_per_task": app_settings.CHECKPOINT_MAX_PER_TASK,
                }
            },
        )

    return SaveCheckpointResult(
        ok=True,
        skipped=False,
        checkpoint_id=checkpoint_id,
        reason=None,
        memory_bytes=memory_bytes,
    )


def load_checkpoint(checkpoint_id: str) -> CheckpointRecord | None:
    init_checkpoint_db()

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM task_checkpoints
            WHERE checkpoint_id = ?
            """,
            (checkpoint_id,),
        ).fetchone()

    if row is None:
        return None

    return _row_to_record(row)


def get_latest_checkpoint(task_id: str) -> CheckpointRecord | None:
    init_checkpoint_db()

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM task_checkpoints
            WHERE task_id = ?
            ORDER BY step DESC, created_at DESC
            LIMIT 1
            """,
            (task_id,),
        ).fetchone()

    if row is None:
        return None

    return _row_to_record(row)


def list_checkpoints(task_id: str, *, limit: int | None = None) -> list[CheckpointRecord]:
    init_checkpoint_db()

    query = """
        SELECT *
        FROM task_checkpoints
        WHERE task_id = ?
        ORDER BY step DESC, created_at DESC
    """
    params: tuple[Any, ...]
    if limit is not None:
        query += " LIMIT ?"
        params = (task_id, int(limit))
    else:
        params = (task_id,)

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()

    return [_row_to_record(row) for row in rows]


def count_checkpoints(task_id: str) -> int:
    init_checkpoint_db()

    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM task_checkpoints WHERE task_id = ?",
            (task_id,),
        ).fetchone()

    return int(row["total"]) if row is not None else 0
