import json
import time

import pytest

from fastapi.testclient import TestClient

from api.main import app
from storage.task_store import (
    TASK_STATUS_COMPLETED,
    create_task,
    update_task,
)


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

    return TestClient(app)



def _collect_stream(client, task_id):

    chunks = []


    with client.stream(
        "GET",
        "/tasks/" + task_id + "/stream",
    ) as response:

        assert response.status_code == 200

        assert "text/event-stream" in response.headers.get(
            "content-type",
            "",
        )


        for line in response.iter_lines():

            if line.startswith("data: "):

                chunks.append(
                    json.loads(line[6:]),
                )


    return chunks



def test_stream_task_not_found(client):

    response = client.get("/tasks/missing-stream-id/stream")

    assert response.status_code == 404



def test_stream_completed_task_replay(client):

    create_task(
        "stream-done",
        "completed question",
        repo_root="/tmp/repo",
        status=TASK_STATUS_COMPLETED,
    )

    update_task(
        "stream-done",
        status=TASK_STATUS_COMPLETED,
        answer="done",
    )

    events = _collect_stream(client, "stream-done")

    assert events[-1]["event"] == "stream_end"

    assert events[-1]["status"] == TASK_STATUS_COMPLETED



def test_stream_running_task_live_events(client, monkeypatch):

    def fake_ask_ai(memory, agent_mode=None):

        return '{"action": "finish", "answer": "stream live"}'


    monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)

    created = client.post(
        "/tasks",
        json={"question": "stream live test"},
    )

    task_id = created.json()["task_id"]

    time.sleep(0.3)

    events = _collect_stream(client, task_id)

    event_types = [item.get("event") for item in events]

    assert "react_step" in event_types or "tool_call" in event_types

    assert "stream_end" in event_types

    assert events[-1]["status"] == TASK_STATUS_COMPLETED
