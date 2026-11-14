"""Task-scoped backup resolver tests (PR-M4)."""

import json
import threading

import pytest

import config.settings as settings
from audit.context import reset_task_id, set_task_id
from context.execution_state import get_execution_state, reset_execution_state
from context.project_context import set_backup_info
from context.tms import (
    BackupRef,
    backup_create_persistence_note,
    has_task_backup_record,
    maybe_persist_global_backup_dual_write,
    reset_mutation_state,
    resolve_task_backup_ref,
)
from context.tms.context import get_shadow, set_shadow
from context.tms.types import empty_mutation_state


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, tmp_path):
    import context.project_context as project_context_module

    backup_file = tmp_path / "last_backup.json"
    monkeypatch.setattr(project_context_module, "BACKUP_STATE_FILE", backup_file)
    monkeypatch.setattr(settings, "BACKUP_STATE_FILE", backup_file)
    project_context_module._last_backup_branch = None
    project_context_module._last_backup_commit = None
    project_context_module._last_original_branch = None

    reset_execution_state()
    reset_mutation_state()
    yield
    reset_execution_state()
    reset_mutation_state()
    project_context_module._last_backup_branch = None
    project_context_module._last_backup_commit = None
    project_context_module._last_original_branch = None


def _set_tms_backup(branch: str, commit: str, original: str = "main") -> None:
    state = get_shadow()
    state.artifacts.backup = BackupRef(
        backup_branch=branch,
        backup_commit=commit,
        original_branch=original,
    )


def test_resolver_flag_off_prefers_global(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "TASK_SCOPED_BACKUP_ENABLED", False)
    set_backup_info("agent-backup/global", "glob1111", "main")
    _set_tms_backup("agent-backup/tms", "tms1111")

    ref = resolve_task_backup_ref(audit=False)

    assert ref is not None
    assert ref.source == "global_file"
    assert ref.backup_branch == "agent-backup/global"


def test_resolver_flag_on_prefers_tms(monkeypatch):
    monkeypatch.setattr(settings, "TASK_SCOPED_BACKUP_ENABLED", True)
    set_backup_info("agent-backup/global", "glob1111", "main")
    _set_tms_backup("agent-backup/task-a", "taskaaaa")

    ref = resolve_task_backup_ref(audit=False)

    assert ref is not None
    assert ref.source == "tms"
    assert ref.backup_branch == "agent-backup/task-a"


def test_resolver_flag_on_falls_back_to_global_when_tms_empty(monkeypatch):
    monkeypatch.setattr(settings, "TASK_SCOPED_BACKUP_ENABLED", True)
    set_backup_info("agent-backup/global", "glob2222", "main")

    ref = resolve_task_backup_ref(audit=False)

    assert ref is not None
    assert ref.source == "global_file"
    assert ref.backup_commit == "glob2222"


def test_resolver_flag_on_legacy_execution_before_global(monkeypatch):
    monkeypatch.setattr(settings, "TASK_SCOPED_BACKUP_ENABLED", True)
    monkeypatch.setattr(settings, "EXECUTION_STATE_DEDUP_ENABLED", True)
    set_backup_info("agent-backup/global", "glob3333", "main")

    state = get_execution_state()
    state.backup_branch = "agent-backup/legacy"
    state.backup_commit = "leg33333"

    ref = resolve_task_backup_ref(audit=False)

    assert ref is not None
    assert ref.source == "legacy_execution"
    assert ref.backup_branch == "agent-backup/legacy"


def test_maybe_persist_global_dual_write_flag_off_writes_global(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "TASK_SCOPED_BACKUP_ENABLED", False)

    maybe_persist_global_backup_dual_write(
        backup_branch="agent-backup/a",
        backup_commit="abc1234",
        original_branch="main",
    )

    assert settings.BACKUP_STATE_FILE.exists()


def test_maybe_persist_global_dual_write_scoped_without_dual_write_skips_global(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "TASK_SCOPED_BACKUP_ENABLED", True)
    monkeypatch.setattr(settings, "BACKUP_GLOBAL_DUAL_WRITE", False)

    maybe_persist_global_backup_dual_write(
        backup_branch="agent-backup/a",
        backup_commit="abc1234",
        original_branch="main",
    )

    assert not settings.BACKUP_STATE_FILE.exists()


def test_has_task_backup_record_uses_resolver(monkeypatch):
    monkeypatch.setattr(settings, "TASK_SCOPED_BACKUP_ENABLED", True)
    assert has_task_backup_record(audit=False) is False
    _set_tms_backup("agent-backup/x", "deadbeef")
    assert has_task_backup_record(audit=False) is True


def test_backup_gate_mismatch_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "TASK_SCOPED_BACKUP_ENABLED", True)
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", tmp_path / "audit.jsonl")

    import audit.audit_log as audit_log_module

    monkeypatch.setattr(audit_log_module, "AUDIT_LOG_FILE", tmp_path / "audit.jsonl")

    _set_tms_backup("agent-backup/tms", "tms1111")
    set_backup_info("agent-backup/global", "glob1111", "main")

    resolve_task_backup_ref(audit=False)

    events = [
        json.loads(line)
        for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    mismatch = [event for event in events if event.get("event") == "backup_gate_mismatch"]
    assert len(mismatch) == 1


def test_backup_create_persistence_note_flag_matrix(monkeypatch):
    monkeypatch.setattr(settings, "TASK_SCOPED_BACKUP_ENABLED", False)
    assert "last_backup.json" in backup_create_persistence_note()

    monkeypatch.setattr(settings, "TASK_SCOPED_BACKUP_ENABLED", True)
    monkeypatch.setattr(settings, "BACKUP_GLOBAL_DUAL_WRITE", False)
    note = backup_create_persistence_note()
    assert "未写入 global last_backup.json" in note

    monkeypatch.setattr(settings, "BACKUP_GLOBAL_DUAL_WRITE", True)
    assert "dual-write" in backup_create_persistence_note()


def test_thread_local_tms_backup_isolation(monkeypatch):
    monkeypatch.setattr(settings, "TASK_SCOPED_BACKUP_ENABLED", True)
    results: dict[str, str | None] = {}
    barrier = threading.Barrier(2)

    def worker(task_id: str, branch: str, commit: str) -> None:
        token = set_task_id(task_id)
        try:
            set_shadow(empty_mutation_state())
            _set_tms_backup(branch, commit)
            barrier.wait(timeout=5)
            ref = resolve_task_backup_ref(audit=False)
            results[task_id] = ref.backup_branch if ref else None
        finally:
            reset_task_id(token)

    threads = [
        threading.Thread(target=worker, args=("task-a", "agent-backup/a", "aaaa1111")),
        threading.Thread(target=worker, args=("task-b", "agent-backup/b", "bbbb2222")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert results["task-a"] == "agent-backup/a"
    assert results["task-b"] == "agent-backup/b"
