"""
C3–C6 integrated API acceptance tests (TestClient, no live server required).
"""

import json
import threading
import time

import pytest

from fastapi.testclient import TestClient

from api.main import app
from storage.task_store import TASK_STATUS_COMPLETED


@pytest.fixture
def acceptance_client(tmp_path, monkeypatch):

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
        10,
    )

    return TestClient(app)



def test_c3_c6_full_api_acceptance_flow(acceptance_client, monkeypatch):

    client = acceptance_client


    # C3: health
    health = client.get("/health")

    assert health.status_code == 200

    assert health.json()["status"] == "ok"


    # C4: create task
    def fake_ask_ai(memory, agent_mode=None):

        return '{"action": "finish", "answer": "acceptance ok"}'


    monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)

    created = client.post(
        "/tasks",
        json={"question": "acceptance flow test"},
    )

    assert created.status_code == 201

    task_id = created.json()["task_id"]

    assert created.json()["status"] == "running"


    # C3: list + get detail
    listed = client.get("/tasks?limit=5")

    assert listed.status_code == 200

    assert any(
        item["task_id"] == task_id
        for item in listed.json()["tasks"]
    )


    for _ in range(50):

        detail = client.get("/tasks/" + task_id)

        if (
            detail.status_code == 200
            and detail.json()["status"] == TASK_STATUS_COMPLETED
        ):

            break

        time.sleep(0.05)

    else:

        pytest.fail("task did not complete")


    assert detail.json()["answer"] == "acceptance ok"


    # C6: report
    report = client.get("/tasks/" + task_id + "/report")

    assert report.status_code == 200

    assert report.json()["task_id"] == task_id

    assert "任务审计摘要" in report.json()["report"]


    # C6: confirm idle
    pending_idle = client.get(
        "/tasks/" + task_id + "/confirm/pending",
    )

    assert pending_idle.status_code == 200

    assert pending_idle.json()["pending"] is False


    # C6: confirm no pending -> 409
    no_pending = client.post(
        "/tasks/" + task_id + "/confirm",
        json={"confirmed": True},
    )

    assert no_pending.status_code == 409


    # C5: stream ends with stream_end
    events = []

    with client.stream(
        "GET",
        "/tasks/" + task_id + "/stream",
    ) as stream:

        assert stream.status_code == 200

        for line in stream.iter_lines():

            if line.startswith("data: "):

                events.append(json.loads(line[6:]))


    assert events[-1]["event"] == "stream_end"

    assert events[-1]["status"] == TASK_STATUS_COMPLETED



def test_c6_confirm_flow_with_pending(acceptance_client):

    client = acceptance_client

    from storage.task_store import create_task

    from api.task_confirm import make_api_confirm_callback


    create_task(
        "accept-confirm",
        "confirm test",
        repo_root="/tmp/repo",
    )

    results = []


    def wait_for_confirm():

        callback = make_api_confirm_callback("accept-confirm")

        results.append(
            callback(
                "write_repo_file",
                {"path": "demo.txt", "content": "x"},
            )
        )


    thread = threading.Thread(target=wait_for_confirm)

    thread.start()

    time.sleep(0.2)

    pending = client.get("/tasks/accept-confirm/confirm/pending")

    assert pending.status_code == 200

    assert pending.json()["pending"] is True

    assert pending.json()["tool"] == "write_repo_file"


    confirmed = client.post(
        "/tasks/accept-confirm/confirm",
        json={"confirmed": True},
    )

    assert confirmed.status_code == 200

    assert confirmed.json()["confirmed"] is True

    thread.join(timeout=3)

    assert results == [True]
