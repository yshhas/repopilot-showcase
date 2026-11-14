import threading
import time

import config.settings as settings
import storage.checkpoint_store as checkpoint_store_module
import storage.task_store as task_store_module
from fastapi.testclient import TestClient

from api.main import app
from storage.checkpoint_store import save_checkpoint
from storage.task_store import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_RUNNING,
    create_task,
    get_task,
    mark_task_cancelled,
    request_cancel,
    update_task,
)


def _patch_api_dbs(tmp_path, monkeypatch):
    db_file = tmp_path / "tasks.db"
    monkeypatch.setattr(settings, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(task_store_module, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(checkpoint_store_module, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(settings, "CHECKPOINT_ENABLED", True)
    return db_file


def _client(tmp_path, monkeypatch):
    _patch_api_dbs(tmp_path, monkeypatch)
    return TestClient(app)


def _seed_checkpoint(task_id, repo_root, *, step=2, memory=None):
    if memory is None:
        memory = [
            {"role": "user", "content": "start"},
            {"role": "assistant", "content": '{"action": "git_status", "args": {}}'},
            {"role": "user", "content": "工具执行结果:\nok"},
        ]

    return save_checkpoint(
        task_id,
        step=step,
        memory=memory,
        agent_mode="full",
        repo_root=str(repo_root),
        context_state={"chars_used": 100, "files_read": ["a.py"]},
    )


def test_cancel_success_sets_flag(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    audit_file = tmp_path / "audit.jsonl"
    import audit.audit_log as audit_log_module

    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", audit_file)
    monkeypatch.setattr(audit_log_module, "AUDIT_LOG_FILE", audit_file)

    create_task("api-cancel-1", "running", repo_root=str(tmp_path))

    response = client.post("/tasks/api-cancel-1/cancel")

    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == "api-cancel-1"
    assert data["status"] == TASK_STATUS_RUNNING
    assert data["cancel_requested"] is True
    assert data["result"] == "success"

    task = get_task("api-cancel-1")
    assert task["cancel_requested"] == 1
    assert task["status"] == TASK_STATUS_RUNNING

    import json

    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    assert lines
    event = json.loads(lines[-1])
    assert event["event"] == "react_step"
    assert event["step"] == "cancel_requested"
    assert event["task_id"] == "api-cancel-1"
    assert event["details"]["reason"] == "user_request"
    blob = json.dumps(event, ensure_ascii=False)
    assert "memory" not in blob.lower() or "memory_bytes" not in blob


def test_cancel_not_found(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post("/tasks/missing-task/cancel")

    assert response.status_code == 404
    assert response.json()["detail"] == "not_found"


def test_cancel_not_running(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    create_task("api-cancel-2", "done", repo_root=str(tmp_path))
    update_task("api-cancel-2", status=TASK_STATUS_COMPLETED, answer="done")

    response = client.post("/tasks/api-cancel-2/cancel")

    assert response.status_code == 409
    assert response.json()["detail"] == "not_running"


def test_cancel_already_requested(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    create_task("api-cancel-3", "dup", repo_root=str(tmp_path))
    request_cancel("api-cancel-3")

    response = client.post("/tasks/api-cancel-3/cancel")

    assert response.status_code == 409
    assert response.json()["detail"] == "already_requested"


def test_resume_not_found(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post("/tasks/missing-task/resume", json={"question": ""})

    assert response.status_code == 404
    assert response.json()["detail"] == "not_found"


def test_resume_no_checkpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    create_task("api-resume-1", "cancelled", repo_root=str(tmp_path))
    mark_task_cancelled("api-resume-1")

    response = client.post("/tasks/api-resume-1/resume", json={"question": ""})

    assert response.status_code == 404
    assert response.json()["detail"] == "no_checkpoint"


def test_resume_repo_root_mismatch(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    other_root = tmp_path / "other"
    other_root.mkdir()
    create_task("api-resume-2", "cancelled", repo_root=str(other_root))
    mark_task_cancelled("api-resume-2")
    _seed_checkpoint("api-resume-2", other_root)

    response = client.post("/tasks/api-resume-2/resume", json={"question": ""})

    assert response.status_code == 409
    assert response.json()["detail"] == "repo_root_mismatch"


def test_resume_already_running(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    create_task("api-resume-3", "running", repo_root=str(tmp_path))

    response = client.post("/tasks/api-resume-3/resume", json={"question": ""})

    assert response.status_code == 409
    assert response.json()["detail"] == "already_running"


def test_resume_not_resumable_completed(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    create_task("api-resume-4", "done", repo_root=str(tmp_path))
    update_task("api-resume-4", status=TASK_STATUS_COMPLETED, answer="done")
    _seed_checkpoint("api-resume-4", tmp_path)

    response = client.post("/tasks/api-resume-4/resume", json={"question": ""})

    assert response.status_code == 409
    assert response.json()["detail"] == "not_resumable"


def test_resume_success_from_cancelled(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    task_id = "api-resume-5"
    create_task(task_id, "cancelled task", repo_root=str(tmp_path))
    mark_task_cancelled(task_id)
    checkpoint = _seed_checkpoint(task_id, tmp_path, step=3)

    def fake_ask_ai(memory, agent_mode=None):
        assert len(memory) == 3
        assert memory[0]["content"] == "start"
        return '{"action": "finish", "answer": "resumed ok"}'

    monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)

    response = client.post(f"/tasks/{task_id}/resume", json={"question": ""})

    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == task_id
    assert data["status"] == TASK_STATUS_RUNNING
    assert data["resumed_from_step"] == 3
    assert data["checkpoint_id"] == checkpoint.checkpoint_id

    deadline = time.time() + 5
    while time.time() < deadline:
        task = get_task(task_id)
        if task["status"] == TASK_STATUS_COMPLETED:
            break
        time.sleep(0.05)

    task = get_task(task_id)
    assert task["status"] == TASK_STATUS_COMPLETED
    assert task["answer"] == "resumed ok"


def test_resume_success_from_failed_max_steps(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    task_id = "api-resume-6"
    create_task(task_id, "failed task", repo_root=str(tmp_path))
    update_task(
        task_id,
        status=TASK_STATUS_FAILED,
        answer="max steps",
    )
    _seed_checkpoint(task_id, tmp_path, step=2)

    monkeypatch.setattr(
        "react_agent.ask_ai",
        lambda memory, agent_mode=None: '{"action": "finish", "answer": "after fail"}',
    )

    response = client.post(f"/tasks/{task_id}/resume", json={"question": ""})

    assert response.status_code == 200

    deadline = time.time() + 5
    while time.time() < deadline:
        task = get_task(task_id)
        if task["status"] == TASK_STATUS_COMPLETED:
            break
        time.sleep(0.05)

    assert get_task(task_id)["answer"] == "after fail"


def test_resume_appends_follow_up_question(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    task_id = "api-resume-7"
    create_task(task_id, "follow up", repo_root=str(tmp_path))
    mark_task_cancelled(task_id)
    _seed_checkpoint(task_id, tmp_path, step=1)

    seen = {}

    def fake_ask_ai(memory, agent_mode=None):
        seen["memory"] = list(memory)
        return '{"action": "finish", "answer": "with follow up"}'

    monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)

    response = client.post(
        f"/tasks/{task_id}/resume",
        json={"question": "continue please"},
    )

    assert response.status_code == 200

    deadline = time.time() + 5
    while time.time() < deadline:
        if get_task(task_id)["status"] == TASK_STATUS_COMPLETED:
            break
        time.sleep(0.05)

    assert seen["memory"][-1]["role"] == "user"
    assert seen["memory"][-1]["content"] == "continue please"


def test_resume_clears_pending_confirmation(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    task_id = "api-resume-8"
    create_task(task_id, "confirm clear", repo_root=str(tmp_path))
    mark_task_cancelled(task_id)
    _seed_checkpoint(task_id, tmp_path, step=1)

    from api.task_confirm import (
        clear_pending_confirmation,
        get_pending_confirmation,
        make_api_confirm_callback,
    )

    callback = make_api_confirm_callback(task_id)

    def worker():
        callback("apply_patch", {"path": "a.txt"})

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    time.sleep(0.05)

    assert get_pending_confirmation(task_id) is not None

    monkeypatch.setattr(
        "react_agent.ask_ai",
        lambda memory, agent_mode=None: '{"action": "finish", "answer": "cleared"}',
    )

    response = client.post(f"/tasks/{task_id}/resume", json={"question": ""})
    assert response.status_code == 200

    deadline = time.time() + 5
    while time.time() < deadline:
        if get_pending_confirmation(task_id) is None:
            break
        time.sleep(0.05)

    clear_pending_confirmation(task_id)
    assert get_pending_confirmation(task_id) is None
