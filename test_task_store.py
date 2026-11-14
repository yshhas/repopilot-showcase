from storage.task_store import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_RUNNING,
    create_task,
    get_task,
    list_tasks,
    update_task,
)


def test_create_and_get_task(tmp_path, monkeypatch):

    db_file = tmp_path / "tasks.db"

    monkeypatch.setattr("storage.task_store.TASK_DB_FILE", db_file)

    create_task(
        "task001",
        "hello task",
        repo_root=str(tmp_path),
        status=TASK_STATUS_RUNNING,
    )

    task = get_task("task001")

    assert task is not None

    assert task["task_id"] == "task001"

    assert task["question"] == "hello task"

    assert task["status"] == TASK_STATUS_RUNNING

    assert task["repo_root"] == str(tmp_path)

    assert task["agent_mode"] == "full"


def test_update_task_status_and_answer(tmp_path, monkeypatch):

    db_file = tmp_path / "tasks.db"

    monkeypatch.setattr("storage.task_store.TASK_DB_FILE", db_file)

    create_task(
        "task002",
        "update me",
        repo_root=str(tmp_path),
    )

    update_task(
        "task002",
        status=TASK_STATUS_COMPLETED,
        answer="done",
    )

    task = get_task("task002")

    assert task["status"] == TASK_STATUS_COMPLETED

    assert task["answer"] == "done"


def test_list_tasks_orders_by_created_at(tmp_path, monkeypatch):

    db_file = tmp_path / "tasks.db"

    monkeypatch.setattr("storage.task_store.TASK_DB_FILE", db_file)

    create_task("t1", "first", repo_root=str(tmp_path))

    create_task("t2", "second", repo_root=str(tmp_path))

    tasks = list_tasks(limit=10)

    assert len(tasks) == 2

    assert tasks[0]["task_id"] == "t2"


def test_react_agent_persists_task(tmp_path, monkeypatch):

    db_file = tmp_path / "tasks.db"

    monkeypatch.setattr("storage.task_store.TASK_DB_FILE", db_file)

    import config.settings as settings

    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)

    def fake_ask_ai(memory, agent_mode=None):

        return '{"action": "finish", "answer": "stored answer"}'


    monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)

    from react_agent import react_agent

    answer, _memory = react_agent(
        "persist test",
        task_id="persist01",
    )

    assert answer == "stored answer"

    task = get_task("persist01")

    assert task is not None

    assert task["question"] == "persist test"

    assert task["status"] == TASK_STATUS_COMPLETED

    assert task["answer"] == "stored answer"
