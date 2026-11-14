import json

import config.settings as settings
import storage.checkpoint_store as checkpoint_store_module
import storage.task_store as task_store_module
from storage.checkpoint_store import (
    get_latest_checkpoint,
    load_checkpoint,
    save_checkpoint,
)
from storage.task_store import create_task


def _patch_checkpoint_db(tmp_path, monkeypatch):
    db_file = tmp_path / "tasks.db"
    monkeypatch.setattr(settings, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(task_store_module, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(checkpoint_store_module, "TASK_DB_FILE", db_file)
    return db_file


def _sample_memory():
    return [
        {"role": "user", "content": "analyze tools"},
        {"role": "assistant", "content": '{"action": "git_status", "args": {}}'},
        {"role": "user", "content": "工具执行结果:\nbranch main"},
    ]


def test_save_and_load_checkpoint_roundtrip(tmp_path, monkeypatch):
    _patch_checkpoint_db(tmp_path, monkeypatch)
    create_task("cp-task-1", "checkpoint test", repo_root=str(tmp_path))

    memory = _sample_memory()
    context_state = {"chars_used": 1200, "files_read": ["tools/a.py"]}
    execution_state = {"patch_applied": False, "backup_branch": "agent-backup/test"}

    result = save_checkpoint(
        "cp-task-1",
        step=3,
        memory=memory,
        agent_mode="readonly",
        repo_root=str(tmp_path),
        context_state=context_state,
        execution_state=execution_state,
    )

    assert result.ok is True
    assert result.skipped is False
    assert result.checkpoint_id
    assert result.memory_bytes is not None
    assert result.memory_bytes > 0

    loaded = load_checkpoint(result.checkpoint_id)
    assert loaded is not None
    assert loaded.task_id == "cp-task-1"
    assert loaded.step == 3
    assert loaded.agent_mode == "readonly"
    assert loaded.repo_root == str(tmp_path)
    assert loaded.memory == memory
    assert loaded.context_state == context_state
    assert loaded.execution_state == execution_state
    assert loaded.mutation_fsm is None
    assert loaded.mutation_state is None


def test_get_latest_checkpoint_returns_highest_step(tmp_path, monkeypatch):
    _patch_checkpoint_db(tmp_path, monkeypatch)
    create_task("cp-task-2", "latest", repo_root=str(tmp_path))

    first = save_checkpoint(
        "cp-task-2",
        step=2,
        memory=[{"role": "user", "content": "step2"}],
        agent_mode="full",
        repo_root=str(tmp_path),
    )
    second = save_checkpoint(
        "cp-task-2",
        step=5,
        memory=[{"role": "user", "content": "step5"}],
        agent_mode="full",
        repo_root=str(tmp_path),
    )

    latest = get_latest_checkpoint("cp-task-2")
    assert latest is not None
    assert latest.checkpoint_id == second.checkpoint_id
    assert latest.step == 5
    assert latest.memory[-1]["content"] == "step5"
    assert load_checkpoint(first.checkpoint_id) is not None


def test_prune_keeps_max_per_task(tmp_path, monkeypatch):
    _patch_checkpoint_db(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "CHECKPOINT_MAX_PER_TASK", 5)
    create_task("cp-task-3", "prune", repo_root=str(tmp_path))

    saved_ids = []
    for step in range(1, 8):
        result = save_checkpoint(
            "cp-task-3",
            step=step,
            memory=[{"role": "user", "content": "step-" + str(step)}],
            agent_mode="full",
            repo_root=str(tmp_path),
        )
        assert result.ok is True
        saved_ids.append(result.checkpoint_id)

    assert checkpoint_store_module.count_checkpoints("cp-task-3") == 5

    remaining = checkpoint_store_module.list_checkpoints("cp-task-3")
    remaining_steps = {item.step for item in remaining}
    assert remaining_steps == {7, 6, 5, 4, 3}

    for stale_id in saved_ids[:2]:
        assert load_checkpoint(stale_id) is None


def test_save_skips_when_memory_too_large(tmp_path, monkeypatch):
    _patch_checkpoint_db(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "CHECKPOINT_MAX_MEMORY_BYTES", 64)
    create_task("cp-task-4", "too large", repo_root=str(tmp_path))

    memory = [{"role": "user", "content": "x" * 256}]
    result = save_checkpoint(
        "cp-task-4",
        step=1,
        memory=memory,
        agent_mode="full",
        repo_root=str(tmp_path),
    )

    assert result.ok is False
    assert result.skipped is True
    assert result.reason == "memory_too_large"
    assert result.checkpoint_id is None
    assert result.memory_bytes is not None
    assert result.memory_bytes > 64
    assert checkpoint_store_module.count_checkpoints("cp-task-4") == 0


def test_save_skips_when_disabled(tmp_path, monkeypatch):
    _patch_checkpoint_db(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "CHECKPOINT_ENABLED", False)
    create_task("cp-task-5", "disabled", repo_root=str(tmp_path))

    result = save_checkpoint(
        "cp-task-5",
        step=1,
        memory=_sample_memory(),
        agent_mode="full",
        repo_root=str(tmp_path),
    )

    assert result.ok is False
    assert result.skipped is True
    assert result.reason == "disabled"
    assert result.checkpoint_id is None
    assert checkpoint_store_module.count_checkpoints("cp-task-5") == 0


def test_load_missing_returns_none(tmp_path, monkeypatch):
    _patch_checkpoint_db(tmp_path, monkeypatch)
    assert load_checkpoint("missing-checkpoint-id") is None
    assert get_latest_checkpoint("missing-task") is None


def test_context_and_execution_state_json_roundtrip(tmp_path, monkeypatch):
    _patch_checkpoint_db(tmp_path, monkeypatch)
    create_task("cp-task-6", "json", repo_root=str(tmp_path))

    context_state = {
        "chars_used": 45000,
        "files_read": ["schemas.py"],
        "index_head_commit": "abc123",
    }
    execution_state = {
        "proposal_digest": "deadbeef",
        "diff_previewed_paths": ["a.py", "b.py"],
        "patch_applied": False,
    }

    result = save_checkpoint(
        "cp-task-6",
        step=4,
        memory=_sample_memory(),
        agent_mode="full",
        repo_root=str(tmp_path),
        context_state=context_state,
        execution_state=execution_state,
    )

    loaded = load_checkpoint(result.checkpoint_id)
    assert loaded is not None
    assert json.loads(json.dumps(loaded.context_state)) == context_state
    assert json.loads(json.dumps(loaded.execution_state)) == execution_state
