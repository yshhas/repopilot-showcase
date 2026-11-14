import pytest

from fastapi.testclient import TestClient

from api.main import app
from config.settings import APP_VERSION
from storage.task_store import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_RUNNING,
    create_task,
)


@pytest.fixture
def client(tmp_path, monkeypatch):

    db_file = tmp_path / "tasks.db"

    monkeypatch.setattr(
        "storage.task_store.TASK_DB_FILE",
        db_file,
    )

    return TestClient(app)



def test_health(client):

    response = client.get("/health")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "ok"

    assert data["version"] == APP_VERSION

    assert data["service"] == "RepoPilot"

    assert data["agent_mode"] in ("full", "readonly")



def test_list_tasks_empty(client):

    response = client.get("/tasks")

    assert response.status_code == 200

    data = response.json()

    assert data["tasks"] == []

    assert data["count"] == 0

    assert data["limit"] == 20



def test_list_tasks_returns_records(client):

    create_task(
        "api-t1",
        "first question",
        repo_root="/tmp/repo",
        status=TASK_STATUS_RUNNING,
    )

    create_task(
        "api-t2",
        "second question",
        repo_root="/tmp/repo",
        status=TASK_STATUS_COMPLETED,
    )

    response = client.get("/tasks?limit=10")

    assert response.status_code == 200

    data = response.json()

    assert data["count"] == 2

    assert data["tasks"][0]["task_id"] == "api-t2"

    assert data["tasks"][1]["task_id"] == "api-t1"



def test_list_tasks_limit_validation(client):

    response = client.get("/tasks?limit=0")

    assert response.status_code == 422



def test_get_task_found(client):

    create_task(
        "api-get-1",
        "hello api",
        repo_root="/tmp/repo",
        status=TASK_STATUS_COMPLETED,
    )

    response = client.get("/tasks/api-get-1")

    assert response.status_code == 200

    data = response.json()

    assert data["task_id"] == "api-get-1"

    assert data["question"] == "hello api"

    assert data["status"] == TASK_STATUS_COMPLETED



def test_get_task_not_found(client):

    response = client.get("/tasks/missing-id")

    assert response.status_code == 404

    assert "missing-id" in response.json()["detail"]
