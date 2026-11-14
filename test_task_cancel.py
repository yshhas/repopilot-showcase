import sqlite3
from datetime import datetime, timezone

import storage.task_store as task_store_module
from storage.task_store import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_RUNNING,
    CancelRequestResult,
    clear_cancel_request,
    create_task,
    get_task,
    is_cancel_requested,
    list_tasks,
    mark_task_cancelled,
    request_cancel,
)


def _patch_task_db(tmp_path, monkeypatch):
    db_file = tmp_path / "tasks.db"
    monkeypatch.setattr(task_store_module, "TASK_DB_FILE", db_file)
    return db_file


def test_request_cancel_sets_flag_on_running_task(tmp_path, monkeypatch):
    _patch_task_db(tmp_path, monkeypatch)
    create_task("cancel-1", "running task", repo_root=str(tmp_path))

    result = request_cancel("cancel-1")

    assert result == CancelRequestResult(ok=True, reason=None)
    assert is_cancel_requested("cancel-1") is True

    task = get_task("cancel-1")
    assert task["status"] == TASK_STATUS_RUNNING
    assert task["cancel_requested"] == 1


def test_clear_cancel_request(tmp_path, monkeypatch):
    _patch_task_db(tmp_path, monkeypatch)
    create_task("cancel-2", "clear flag", repo_root=str(tmp_path))
    request_cancel("cancel-2")

    assert clear_cancel_request("cancel-2") is True
    assert is_cancel_requested("cancel-2") is False
    assert get_task("cancel-2")["cancel_requested"] == 0


def test_mark_task_cancelled_migrates_status(tmp_path, monkeypatch):
    _patch_task_db(tmp_path, monkeypatch)
    create_task("cancel-3", "to cancel", repo_root=str(tmp_path))
    request_cancel("cancel-3")

    mark_task_cancelled("cancel-3", answer="用户已取消")

    task = get_task("cancel-3")
    assert task["status"] == TASK_STATUS_CANCELLED
    assert task["answer"] == "用户已取消"
    assert task["cancel_requested"] == 0
    assert is_cancel_requested("cancel-3") is False


def test_old_db_without_cancel_requested_column_migrates(tmp_path, monkeypatch):
    db_file = _patch_task_db(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(db_file)
    conn.execute(
        """
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT,
            repo_root TEXT NOT NULL,
            agent_mode TEXT NOT NULL DEFAULT 'full',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO tasks (
            task_id, status, question, answer, repo_root,
            agent_mode, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy-1",
            TASK_STATUS_RUNNING,
            "legacy task",
            None,
            str(tmp_path),
            "full",
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()

    task = get_task("legacy-1")
    assert task is not None
    assert "cancel_requested" in task
    assert task["cancel_requested"] == 0

    result = request_cancel("legacy-1")
    assert result.ok is True
    assert get_task("legacy-1")["cancel_requested"] == 1


def test_request_cancel_rejects_not_running(tmp_path, monkeypatch):
    _patch_task_db(tmp_path, monkeypatch)
    create_task("cancel-4", "done", repo_root=str(tmp_path))
    task_store_module.update_task(
        "cancel-4",
        status=TASK_STATUS_COMPLETED,
        answer="finished",
    )

    result = request_cancel("cancel-4")
    assert result.ok is False
    assert result.reason == "not_running"


def test_request_cancel_rejects_duplicate_request(tmp_path, monkeypatch):
    _patch_task_db(tmp_path, monkeypatch)
    create_task("cancel-5", "duplicate", repo_root=str(tmp_path))

    first = request_cancel("cancel-5")
    second = request_cancel("cancel-5")

    assert first.ok is True
    assert second.ok is False
    assert second.reason == "already_requested"
    assert is_cancel_requested("cancel-5") is True


def test_request_cancel_rejects_already_cancelled(tmp_path, monkeypatch):
    _patch_task_db(tmp_path, monkeypatch)
    create_task("cancel-6", "cancelled", repo_root=str(tmp_path))
    mark_task_cancelled("cancel-6")

    result = request_cancel("cancel-6")
    assert result.ok is False
    assert result.reason == "already_cancelled"


def test_request_cancel_not_found(tmp_path, monkeypatch):
    _patch_task_db(tmp_path, monkeypatch)

    result = request_cancel("missing-task")
    assert result.ok is False
    assert result.reason == "not_found"


def test_cancelled_task_visible_in_list_tasks(tmp_path, monkeypatch):
    _patch_task_db(tmp_path, monkeypatch)
    create_task("cancel-7", "listed", repo_root=str(tmp_path))
    mark_task_cancelled("cancel-7")

    tasks = list_tasks(limit=10)
    match = next(item for item in tasks if item["task_id"] == "cancel-7")

    assert match["status"] == TASK_STATUS_CANCELLED
    assert match["cancel_requested"] == 0
