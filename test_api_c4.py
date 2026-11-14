import time

import pytest

from fastapi.testclient import TestClient

from api.main import app
from storage.task_store import TASK_STATUS_COMPLETED, TASK_STATUS_RUNNING, get_task


@pytest.fixture
def client(tmp_path, monkeypatch):

    db_file = tmp_path / "tasks.db"

    monkeypatch.setattr(
        "storage.task_store.TASK_DB_FILE",
        db_file,
    )

    return TestClient(app)



def test_create_task_returns_running(client, monkeypatch):

    def fake_ask_ai(memory, agent_mode=None):

        return '{"action": "finish", "answer": "api done"}'


    monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)

    response = client.post(
        "/tasks",
        json={"question": "hello from api"},
    )

    assert response.status_code == 201

    data = response.json()

    assert data["status"] == TASK_STATUS_RUNNING

    assert len(data["task_id"]) == 8

    assert "accepted" in data["message"].lower()


    task_id = data["task_id"]


    for _ in range(50):

        task = get_task(task_id)

        if task and task["status"] == TASK_STATUS_COMPLETED:

            break

        time.sleep(0.05)

    else:

        pytest.fail("task did not complete in time")


    task = get_task(task_id)

    assert task["question"] == "hello from api"

    assert task["answer"] == "api done"



def test_create_task_empty_question_rejected(client):

    response = client.post(
        "/tasks",
        json={"question": "   "},
    )

    assert response.status_code == 422



def test_create_task_then_get_by_id(client, monkeypatch):

    def fake_ask_ai(memory, agent_mode=None):

        return '{"action": "finish", "answer": "ok"}'


    monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)

    created = client.post(
        "/tasks",
        json={"question": "get by id test"},
    )

    task_id = created.json()["task_id"]


    for _ in range(50):

        detail = client.get("/tasks/" + task_id)

        if detail.status_code == 200 and detail.json()["status"] == TASK_STATUS_COMPLETED:

            break

        time.sleep(0.05)


    detail = client.get("/tasks/" + task_id)

    assert detail.status_code == 200

    assert detail.json()["task_id"] == task_id

    assert detail.json()["answer"] == "ok"



def test_create_task_with_readonly_mode(client, monkeypatch):

    def fake_ask_ai(memory, agent_mode=None):

        return '{"action": "finish", "answer": "readonly ok"}'


    monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)

    response = client.post(
        "/tasks",
        json={
            "question": "readonly task",
            "mode": "readonly",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["agent_mode"] == "readonly"

    task_id = data["task_id"]

    for _ in range(50):

        task = get_task(task_id)

        if task and task["status"] == TASK_STATUS_COMPLETED:

            break

        time.sleep(0.05)

    task = get_task(task_id)

    assert task["agent_mode"] == "readonly"



def test_create_task_invalid_mode_rejected(client):

    response = client.post(
        "/tasks",
        json={
            "question": "bad mode",
            "mode": "invalid",
        },
    )

    assert response.status_code == 422
