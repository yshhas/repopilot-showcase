import threading
import time

import pytest

from fastapi.testclient import TestClient

from api.main import app
from api.task_confirm import make_api_confirm_callback
from storage.task_store import TASK_STATUS_COMPLETED, create_task, update_task


@pytest.fixture
def client(tmp_path, monkeypatch):

    db_file = tmp_path / "tasks.db"

    audit_file = tmp_path / "audit.jsonl"

    monkeypatch.setattr(
        "storage.task_store.TASK_DB_FILE",
        db_file,
    )

    monkeypatch.setattr(
        "audit.audit_log.AUDIT_LOG_FILE",
        audit_file,
    )

    monkeypatch.setattr(
        "audit.task_report.AUDIT_LOG_FILE",
        audit_file,
    )

    monkeypatch.setattr(
        "api.task_confirm.API_CONFIRM_TIMEOUT_SECONDS",
        5,
    )

    return TestClient(app)



def test_get_task_report(client):

    create_task(
        "report-api-1",
        "report question",
        repo_root="/tmp/repo",
        status=TASK_STATUS_COMPLETED,
    )

    update_task(
        "report-api-1",
        status=TASK_STATUS_COMPLETED,
        answer="done",
    )

    response = client.get("/tasks/report-api-1/report")

    assert response.status_code == 200

    data = response.json()

    assert data["task_id"] == "report-api-1"

    assert "任务审计摘要" in data["report"]



def test_get_task_report_not_found(client):

    response = client.get("/tasks/missing-report/report")

    assert response.status_code == 404



def test_confirm_no_pending_returns_409(client):

    create_task(
        "confirm-none",
        "q",
        repo_root="/tmp/repo",
    )

    response = client.post(
        "/tasks/confirm-none/confirm",
        json={"confirmed": True},
    )

    assert response.status_code == 409



def test_get_pending_confirm_when_idle(client):

    create_task(
        "pending-idle",
        "q",
        repo_root="/tmp/repo",
    )

    response = client.get("/tasks/pending-idle/confirm/pending")

    assert response.status_code == 200

    data = response.json()

    assert data["pending"] is False



def test_api_confirm_callback_accepts_via_http(client):

    create_task(
        "confirm-flow",
        "q",
        repo_root="/tmp/repo",
    )

    results = []


    def run_callback():

        callback = make_api_confirm_callback("confirm-flow")

        results.append(
            callback(
                "write_repo_file",
                {"path": "test.txt", "content": "hello"},
            )
        )


    thread = threading.Thread(target=run_callback)

    thread.start()

    time.sleep(0.2)

    pending = client.get("/tasks/confirm-flow/confirm/pending")

    assert pending.status_code == 200

    assert pending.json()["pending"] is True

    assert pending.json()["tool"] == "write_repo_file"


    response = client.post(
        "/tasks/confirm-flow/confirm",
        json={"confirmed": True},
    )

    assert response.status_code == 200

    assert response.json()["confirmed"] is True

    thread.join(timeout=3)

    assert results == [True]



def test_api_confirm_callback_rejects_via_http(client):

    create_task(
        "confirm-reject",
        "q",
        repo_root="/tmp/repo",
    )

    results = []


    def run_callback():

        callback = make_api_confirm_callback("confirm-reject")

        results.append(
            callback(
                "write_repo_file",
                {"path": "test.txt"},
            )
        )


    thread = threading.Thread(target=run_callback)

    thread.start()

    time.sleep(0.2)

    response = client.post(
        "/tasks/confirm-reject/confirm",
        json={"confirmed": False},
    )

    assert response.status_code == 200

    thread.join(timeout=3)

    assert results == [False]
