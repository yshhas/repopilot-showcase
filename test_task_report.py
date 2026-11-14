import json

from audit.task_report import (
    build_task_report,
    generate_task_report,
    load_events_for_task,
)


def _write_audit(path, records):

    with open(path, "w", encoding="utf-8") as f:

        for record in records:

            f.write(
                json.dumps(record, ensure_ascii=False)
                + "\n"
            )



def test_load_events_for_task_filters_by_id(tmp_path):

    audit_file = tmp_path / "audit.jsonl"

    _write_audit(
        audit_file,
        [
            {
                "time": "2026-07-18T10:00:00+00:00",
                "event": "react_step",
                "task_id": "abc123",
                "step": "task_start",
            },
            {
                "time": "2026-07-18T10:00:01+00:00",
                "event": "tool_call",
                "task_id": "other",
                "tool": "calculator",
            },
            {
                "time": "2026-07-18T10:00:02+00:00",
                "event": "tool_call",
                "task_id": "abc123",
                "tool": "calculator",
                "status": "success",
            },
        ],
    )

    with open(audit_file, "a", encoding="utf-8") as f:

        f.write("not valid json\n")

    events = load_events_for_task(
        "abc123",
        audit_file=audit_file,
    )

    assert len(events) == 2

    assert events[0]["step"] == "task_start"

    assert events[1]["tool"] == "calculator"



def test_build_task_report_includes_sections(tmp_path):

    events = [
        {
            "time": "2026-07-18T10:00:00+00:00",
            "event": "react_step",
            "task_id": "r1",
            "step": "task_start",
            "details": {"question": "hello"},
        },
        {
            "time": "2026-07-18T10:00:01+00:00",
            "event": "react_step",
            "task_id": "r1",
            "step": "tool_request",
            "details": {"action": "calculator"},
        },
        {
            "time": "2026-07-18T10:00:01+00:00",
            "event": "tool_call",
            "task_id": "r1",
            "tool": "calculator",
            "status": "success",
            "duration_ms": 1.5,
        },
        {
            "time": "2026-07-18T10:00:02+00:00",
            "event": "react_step",
            "task_id": "r1",
            "step": "finish",
            "details": {"answer": "done"},
        },
        {
            "time": "2026-07-18T10:00:02+00:00",
            "event": "file_write",
            "task_id": "r1",
            "path": "demo.py",
            "bytes": 42,
            "created": True,
        },
    ]

    task_record = {
        "task_id": "r1",
        "status": "completed",
        "question": "hello",
        "answer": "done",
    }

    report = build_task_report(
        "r1",
        events,
        task_record=task_record,
    )

    assert "===== 任务审计摘要 =====" in report

    assert "任务 ID: r1" in report

    assert "状态: completed" in report

    assert "问题: hello" in report

    assert "回答: done" in report

    assert "--- ReAct 流程 ---" in report

    assert "任务开始: hello" in report

    assert "--- 工具调用 ---" in report

    assert "calculator: 调用 1 次" in report

    assert "--- 写入 / Diff / Patch / Git / 确认 ---" in report

    assert "创建文件 demo.py" in report

    assert "===== 报告结束 =====" in report



def test_build_task_report_empty_events():

    report = build_task_report(
        "missing",
        [],
        task_record=None,
    )

    assert "未找到该 task_id 的审计记录" in report



def test_generate_task_report_with_task_store(
    tmp_path,
    monkeypatch,
):

    audit_file = tmp_path / "audit.jsonl"

    db_file = tmp_path / "tasks.db"

    monkeypatch.setattr(
        "storage.task_store.TASK_DB_FILE",
        db_file,
    )

    _write_audit(
        audit_file,
        [
            {
                "time": "2026-07-18T12:00:00+00:00",
                "event": "react_step",
                "task_id": "gen01",
                "step": "task_start",
                "details": {"question": "test q"},
            },
            {
                "time": "2026-07-18T12:00:01+00:00",
                "event": "react_step",
                "task_id": "gen01",
                "step": "finish",
                "details": {"answer": "test a"},
            },
        ],
    )

    from storage.task_store import create_task

    create_task(
        "gen01",
        "test q",
        repo_root=str(tmp_path),
        status="completed",
    )

    report = generate_task_report(
        "gen01",
        audit_file=audit_file,
    )

    assert "任务 ID: gen01" in report

    assert "问题: test q" in report

    assert "任务完成: test a" in report


def test_build_task_report_includes_diff_preview_and_patch_apply():

    events = [
        {
            "time": "2026-07-18T10:00:00+00:00",
            "event": "diff_preview",
            "task_id": "diff1",
            "path": "sample.py",
            "status": "success",
            "lines_added": 2,
            "lines_removed": 1,
            "hunk_count": 1,
        },
        {
            "time": "2026-07-18T10:00:01+00:00",
            "event": "patch_apply",
            "task_id": "diff1",
            "path": "sample.py",
            "status": "success",
            "created": False,
            "backup_present": True,
            "backup_branch": "agent-backup/20260718-100000",
            "lines_added": 2,
            "lines_removed": 1,
        },
        {
            "time": "2026-07-18T10:00:02+00:00",
            "event": "patch_apply",
            "task_id": "diff1",
            "path": "other.py",
            "status": "failed",
            "error": "patch 预检失败 (git apply --check): corrupt patch",
        },
    ]

    report = build_task_report("diff1", events)

    assert "diff_preview: 1" in report

    assert "patch_apply: 2" in report

    assert "Diff 预览 sample.py" in report

    assert "Patch 应用成功 (修改) sample.py" in report

    assert "agent-backup/20260718-100000" in report

    assert "Patch 应用失败 other.py" in report

    assert "--- a/" not in report

    assert "+++ b/" not in report


def test_build_task_report_renders_batch_diff_preview_success():
    events = [
        {
            "time": "2026-07-18T10:00:00+00:00",
            "event": "diff_preview",
            "task_id": "batch1",
            "path": "a.py",
            "file_count": 3,
            "paths": "a.py, b.py, c.py",
            "status": "success",
            "lines_added": 12,
            "lines_removed": 4,
            "hunk_count": 5,
        },
    ]

    report = build_task_report("batch1", events)

    assert "Diff batch (3 files): a.py, b.py, c.py · +12 / -4 · 5 hunks" in report
    assert "Diff 预览 a.py" not in report
    assert "--- a/" not in report


def test_build_task_report_renders_batch_diff_preview_failure():
    events = [
        {
            "time": "2026-07-18T10:00:00+00:00",
            "event": "diff_preview",
            "task_id": "batch2",
            "path": "a.py",
            "file_count": 2,
            "paths": "a.py, b.py",
            "status": "failed",
            "failed_path": "b.py",
            "error": "路径越界",
        },
    ]

    report = build_task_report("batch2", events)

    assert "Diff batch 失败 (2 files): a.py, b.py · failed_path=b.py · 路径越界" in report


def test_build_task_report_renders_batch_patch_apply_success():
    events = [
        {
            "time": "2026-07-18T10:00:00+00:00",
            "event": "patch_apply",
            "task_id": "batch3",
            "path": "a.py",
            "file_count": 3,
            "paths": "a.py, b.py, c.py",
            "status": "success",
            "lines_added": 12,
            "lines_removed": 4,
            "backup_present": True,
            "backup_branch": "agent-backup/20260718-100000",
        },
    ]

    report = build_task_report("batch3", events)

    assert (
        "Patch batch (3 files): a.py, b.py, c.py · +12 / -4 · success · "
        "有备份 (agent-backup/20260718-100000)"
    ) in report
    assert "Patch 应用成功 (修改) a.py" not in report


def test_build_task_report_renders_batch_patch_apply_failure():
    events = [
        {
            "time": "2026-07-18T10:00:01+00:00",
            "event": "patch_apply",
            "task_id": "batch4",
            "path": "a.py",
            "file_count": 3,
            "paths": "a.py, b.py, c.py",
            "status": "failed",
            "failed_path": "c.py",
            "error": "patch 预检失败 (git apply --check): corrupt patch",
        },
    ]

    report = build_task_report("batch4", events)

    assert (
        "Patch batch 失败 (3 files): a.py, b.py, c.py · failed_path=c.py · "
        "patch 预检失败 (git apply --check): corrupt patch"
    ) in report


def test_build_task_report_batch_paths_truncation_passthrough():
    events = [
        {
            "time": "2026-07-18T10:00:00+00:00",
            "event": "patch_apply",
            "task_id": "batch5",
            "path": "f0.txt",
            "file_count": 6,
            "paths": "f0.txt, f1.txt, f2.txt, f3.txt, f4.txt, ... +1 more",
            "status": "success",
            "lines_added": 6,
            "lines_removed": 0,
            "backup_present": False,
        },
    ]

    report = build_task_report("batch5", events)

    assert "... +1 more" in report
    assert "Patch batch (6 files):" in report


def test_build_task_report_mixed_single_and_batch_events():
    events = [
        {
            "time": "2026-07-18T10:00:00+00:00",
            "event": "diff_preview",
            "task_id": "mixed1",
            "path": "single.py",
            "status": "success",
            "lines_added": 1,
            "lines_removed": 0,
            "hunk_count": 1,
        },
        {
            "time": "2026-07-18T10:00:01+00:00",
            "event": "patch_apply",
            "task_id": "mixed1",
            "path": "a.py",
            "file_count": 2,
            "paths": "a.py, b.py",
            "status": "success",
            "lines_added": 4,
            "lines_removed": 1,
            "backup_present": True,
            "backup_branch": "agent-backup/test",
        },
    ]

    report = build_task_report("mixed1", events)

    assert "Diff 预览 single.py: +1 / -0 行, 1 hunks" in report
    assert "Patch batch (2 files): a.py, b.py · +4 / -1 · success · 有备份 (agent-backup/test)" in report


def test_build_task_report_file_count_one_uses_single_file_format():
    events = [
        {
            "time": "2026-07-18T10:00:00+00:00",
            "event": "patch_apply",
            "task_id": "one1",
            "path": "sample.py",
            "file_count": 1,
            "paths": "sample.py",
            "status": "success",
            "created": False,
            "backup_present": True,
            "backup_branch": "agent-backup/test",
            "lines_added": 2,
            "lines_removed": 1,
        },
    ]

    report = build_task_report("one1", events)

    assert "Patch 应用成功 (修改) sample.py" in report
    assert "Patch batch" not in report


def test_build_task_report_includes_cancel_checkpoint_summaries():
    events = [
        {
            "time": "2026-07-18T10:00:00+00:00",
            "event": "react_step",
            "task_id": "cp1",
            "step": "cancel_requested",
            "details": {"react_step": 2, "reason": "user_request"},
        },
        {
            "time": "2026-07-18T10:00:01+00:00",
            "event": "react_step",
            "task_id": "cp1",
            "step": "checkpoint_saved",
            "details": {
                "react_step": 3,
                "checkpoint_id": "abcd1234efgh5678",
                "memory_bytes": 1200,
            },
        },
        {
            "time": "2026-07-18T10:00:02+00:00",
            "event": "react_step",
            "task_id": "cp1",
            "step": "task_cancelled",
            "details": {"react_step": 4, "reason": "user_request"},
        },
        {
            "time": "2026-07-18T10:00:03+00:00",
            "event": "react_step",
            "task_id": "cp1",
            "step": "task_resumed",
            "details": {"react_step": 4, "agent_mode": "full"},
        },
    ]

    report = build_task_report("cp1", events)

    assert "Cancel 请求 · step 2" in report
    assert "Checkpoint 保存 · step 3 · id abcd1234..." in report
    assert "任务取消 · step 4" in report
    assert "任务恢复 · 从 step 4 继续" in report


def test_preview_unified_diff_writes_diff_preview_audit(tmp_path, monkeypatch):

    monkeypatch.setenv("REPO_ROOT", str(tmp_path))

    import config.settings as settings

    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)

    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", tmp_path / "audit.jsonl")

    import security.path_guard as path_guard

    monkeypatch.setattr(path_guard, "REPO_ROOT", tmp_path)

    import audit.audit_log as audit_log_module

    monkeypatch.setattr(audit_log_module, "AUDIT_LOG_FILE", tmp_path / "audit.jsonl")

    sample = tmp_path / "sample.txt"

    sample.write_text("original\n", encoding="utf-8")

    from tools.diff_engine import preview_unified_diff
    from tools.result_schema import tool_result_message

    result = preview_unified_diff("sample.txt", "updated\n")

    assert "Unified diff 预览" in tool_result_message(result)

    records = [
        json.loads(line)
        for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    preview_events = [
        record for record in records if record.get("event") == "diff_preview"
    ]

    assert preview_events

    event = preview_events[-1]

    assert event["path"] == "sample.txt"

    assert event["status"] == "success"

    assert event["lines_added"] == 1

    assert "preview" not in event

    assert "new_content" not in event

    assert "--- a/" not in json.dumps(event)
