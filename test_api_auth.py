import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):

    db_file = tmp_path / "tasks.db"

    monkeypatch.setattr(
        "storage.task_store.TASK_DB_FILE",
        db_file,
    )

    return TestClient(app)


def test_api_key_disabled_allows_tasks_without_header(client, monkeypatch):

    monkeypatch.setattr("config.settings.API_KEY", "")

    response = client.get("/tasks")

    assert response.status_code == 200


def test_api_key_enabled_rejects_missing_header(client, monkeypatch):

    monkeypatch.setattr("config.settings.API_KEY", "test-secret-key")

    response = client.get("/tasks")

    assert response.status_code == 401

    assert response.json()["detail"] == "Invalid or missing API key"


def test_api_key_enabled_accepts_valid_header(client, monkeypatch):

    monkeypatch.setattr("config.settings.API_KEY", "test-secret-key")

    response = client.get(
        "/tasks",
        headers={"X-API-Key": "test-secret-key"},
    )

    assert response.status_code == 200


def test_health_exempt_when_api_key_enabled(client, monkeypatch):

    monkeypatch.setattr("config.settings.API_KEY", "test-secret-key")

    response = client.get("/health")

    assert response.status_code == 200

    assert response.json()["status"] == "ok"


def test_api_key_enabled_rejects_wrong_header(client, monkeypatch):

    monkeypatch.setattr("config.settings.API_KEY", "test-secret-key")

    response = client.post(
        "/tasks",
        json={"question": "hello"},
        headers={"X-API-Key": "wrong-key"},
    )

    assert response.status_code == 401


def test_api_key_empty_string_same_as_unset(client, monkeypatch):

    monkeypatch.setattr("config.settings.API_KEY", "")

    response = client.get("/tasks")

    assert response.status_code == 200

    response = client.post(
        "/tasks",
        json={"question": "no auth"},
    )

    assert response.status_code == 201


def test_api_key_whitespace_only_same_as_unset(client, monkeypatch):

    monkeypatch.setattr("config.settings.API_KEY", "   ")

    response = client.get("/tasks")

    assert response.status_code == 200


def test_401_does_not_leak_configured_key(client, monkeypatch):

    secret = "super-secret-server-key-do-not-leak"

    monkeypatch.setattr("config.settings.API_KEY", secret)

    response = client.get("/tasks")

    assert response.status_code == 401

    body = response.text

    assert secret not in body

    assert response.json() == {"detail": "Invalid or missing API key"}


def test_task_get_and_sse_with_valid_api_key(client, monkeypatch):

    monkeypatch.setattr("config.settings.API_KEY", "test-secret-key")

    headers = {"X-API-Key": "test-secret-key"}

    create_resp = client.post(
        "/tasks",
        json={"question": "auth sse test"},
        headers=headers,
    )

    assert create_resp.status_code == 201

    task_id = create_resp.json()["task_id"]

    get_resp = client.get(
        "/tasks/" + task_id,
        headers=headers,
    )

    assert get_resp.status_code == 200

    assert get_resp.json()["task_id"] == task_id

    stream_resp = client.get(
        "/tasks/" + task_id + "/stream",
        headers=headers,
    )

    assert stream_resp.status_code == 200

    assert "text/event-stream" in stream_resp.headers.get(
        "content-type",
        "",
    )


def test_sse_returns_401_without_header_when_auth_enabled(client, monkeypatch):

    monkeypatch.setattr("config.settings.API_KEY", "test-secret-key")

    response = client.get("/tasks/some-id/stream")

    assert response.status_code == 401
