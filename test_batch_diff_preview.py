import json

import pytest

import config.settings as settings
from schemas import FileChange
from tools.diff_engine import generate_unified_diff, preview_unified_diff_batch
from tools.result_schema import tool_result_message
from tools.tool_manager import run_tool


@pytest.fixture(autouse=True)
def _disable_fsm_for_batch_diff_unit_tests(disable_mutation_fsm):
    return disable_mutation_fsm


def _setup_repo(tmp_path, monkeypatch, *, audit=True):
    monkeypatch.setenv("REPO_ROOT", str(tmp_path))

    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)

    import context.project_context as project_context_module

    monkeypatch.setattr(project_context_module, "REPO_ROOT", tmp_path)

    import security.path_guard as path_guard

    monkeypatch.setattr(path_guard, "REPO_ROOT", tmp_path)

    if audit:
        audit_file = tmp_path / "audit.jsonl"
        monkeypatch.setattr(settings, "AUDIT_LOG_FILE", audit_file)

        import audit.audit_log as audit_log_module

        monkeypatch.setattr(audit_log_module, "AUDIT_LOG_FILE", audit_file)

        return audit_file

    return None


def test_preview_unified_diff_batch_three_files(tmp_path, monkeypatch):
    _setup_repo(tmp_path, monkeypatch, audit=False)

    (tmp_path / "a.txt").write_text("a-old\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b-old\n", encoding="utf-8")
    (tmp_path / "c.txt").write_text("c-old\n", encoding="utf-8")

    result = preview_unified_diff_batch(
        [
            FileChange(path="a.txt", new_content="a-new\n"),
            FileChange(path="b.txt", new_content="b-new\n"),
            FileChange(path="c.txt", new_content="c-new\n"),
        ],
    )

    assert "Unified diff 批量预览" in tool_result_message(result)
    assert "文件数: 3" in tool_result_message(result)
    assert "a.txt" in tool_result_message(result)
    assert "b.txt" in tool_result_message(result)
    assert "c.txt" in tool_result_message(result)
    assert "--- a/a.txt" in tool_result_message(result)
    assert "--- a/b.txt" in tool_result_message(result)
    assert "--- a/c.txt" in tool_result_message(result)
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "a-old\n"


def test_run_tool_generate_unified_diff_with_changes(tmp_path, monkeypatch):
    _setup_repo(tmp_path, monkeypatch, audit=False)

    (tmp_path / "a.txt").write_text("a-old\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b-old\n", encoding="utf-8")

    result = run_tool(
        "generate_unified_diff",
        {
            "changes": [
                {"path": "a.txt", "new_content": "a-new\n"},
                {"path": "b.txt", "new_content": "b-new\n"},
            ],
        },
    )

    assert "Unified diff 批量预览" in tool_result_message(result)
    assert "文件数: 2" in tool_result_message(result)
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "a-old\n"


def test_batch_preview_fails_when_one_file_invalid(tmp_path, monkeypatch):
    _setup_repo(tmp_path, monkeypatch, audit=False)

    (tmp_path / "good.txt").write_text("good\n", encoding="utf-8")

    result = preview_unified_diff_batch(
        [
            FileChange(path="good.txt", new_content="good-new\n"),
            FileChange(path="../outside.txt", new_content="bad\n"),
        ],
    )

    assert "越界" in tool_result_message(result)
    assert (tmp_path / "good.txt").read_text(encoding="utf-8") == "good\n"


def test_batch_preview_fails_on_empty_diff(tmp_path, monkeypatch):
    _setup_repo(tmp_path, monkeypatch, audit=False)

    (tmp_path / "same.txt").write_text("same\n", encoding="utf-8")

    result = preview_unified_diff_batch(
        [
            FileChange(path="same.txt", new_content="same\n"),
        ],
    )

    assert "无变化" in tool_result_message(result)


def test_batch_preview_fails_on_batch_changed_lines_limit(tmp_path, monkeypatch):
    _setup_repo(tmp_path, monkeypatch, audit=False)
    monkeypatch.setattr(settings, "PATCH_MAX_CHANGED_LINES", 4)

    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")

    result = preview_unified_diff_batch(
        [
        FileChange(path="a.txt", new_content="a\nline2\nline3\nline4\n"),
        FileChange(path="b.txt", new_content="b\nline2\nline3\nline4\n"),
        ],
    )

    assert "变更行数超过上限" in tool_result_message(result)


def test_changes_one_matches_legacy_preview(tmp_path, monkeypatch):
    _setup_repo(tmp_path, monkeypatch, audit=False)

    sample = tmp_path / "sample.txt"
    sample.write_text("original\n", encoding="utf-8")

    legacy = run_tool(
        "generate_unified_diff",
        {"path": "sample.txt", "new_content": "updated\n"},
    )
    batch_one = run_tool(
        "generate_unified_diff",
        {
            "changes": [
                {"path": "sample.txt", "new_content": "updated\n"},
            ],
        },
    )

    assert legacy == batch_one


def test_batch_preview_writes_batch_audit_fields(tmp_path, monkeypatch):
    audit_file = _setup_repo(tmp_path, monkeypatch, audit=True)

    (tmp_path / "a.txt").write_text("a-old\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b-old\n", encoding="utf-8")

    result = generate_unified_diff(
        changes=[
            {"path": "a.txt", "new_content": "a-new\n"},
            {"path": "b.txt", "new_content": "b-new\n"},
        ],
    )

    assert "Unified diff 批量预览" in tool_result_message(result)

    records = [
        json.loads(line)
        for line in audit_file.read_text(encoding="utf-8").splitlines()
    ]
    event = records[-1]

    assert event["event"] == "diff_preview"
    assert event["status"] == "success"
    assert event["file_count"] == 2
    assert "a.txt" in event["paths"]
    assert "b.txt" in event["paths"]
    assert "preview" not in event
    assert "new_content" not in event
    assert "--- a/" not in json.dumps(event)


def test_single_file_audit_keeps_v04_shape(tmp_path, monkeypatch):
    audit_file = _setup_repo(tmp_path, monkeypatch, audit=True)

    sample = tmp_path / "sample.txt"
    sample.write_text("original\n", encoding="utf-8")

    generate_unified_diff(path="sample.txt", new_content="updated\n")

    event = json.loads(audit_file.read_text(encoding="utf-8").splitlines()[-1])

    assert event["path"] == "sample.txt"
    assert event["status"] == "success"
    assert "file_count" not in event
    assert "paths" not in event


def test_batch_audit_paths_truncated_after_five(tmp_path, monkeypatch):
    audit_file = _setup_repo(tmp_path, monkeypatch, audit=True)

    changes = []

    for index in range(6):
        name = "f" + str(index) + ".txt"
        (tmp_path / name).write_text("old\n", encoding="utf-8")
        changes.append({"path": name, "new_content": "new" + str(index) + "\n"})

    generate_unified_diff(changes=changes)

    event = json.loads(audit_file.read_text(encoding="utf-8").splitlines()[-1])

    assert event["file_count"] == 6
    assert "+1 more" in event["paths"]


def test_batch_preview_blocks_sensitive_path(tmp_path, monkeypatch):
    _setup_repo(tmp_path, monkeypatch, audit=False)

    (tmp_path / "good.txt").write_text("good\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")

    result = preview_unified_diff_batch(
        [
            FileChange(path="good.txt", new_content="good-new\n"),
            FileChange(path=".env", new_content="SECRET=2\n"),
        ],
    )

    assert "敏感" in tool_result_message(result)


def test_batch_preview_rejects_oversized_content(tmp_path, monkeypatch):
    _setup_repo(tmp_path, monkeypatch, audit=False)
    monkeypatch.setattr(settings, "MAX_WRITE_BYTES", 8)

    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")

    result = preview_unified_diff_batch(
        [FileChange(path="a.txt", new_content="0123456789\n")],
    )

    assert "写入内容过大" in tool_result_message(result)


def test_run_tool_rejects_mixed_legacy_and_changes():
    result = run_tool(
        "generate_unified_diff",
        {
            "path": "a.txt",
            "new_content": "a\n",
            "changes": [{"path": "b.txt", "new_content": "b\n"}],
        },
    )

    assert "参数错误" in tool_result_message(result)


def test_run_tool_generate_unified_diff_readonly_with_changes(tmp_path, monkeypatch):
    from audit.context import reset_agent_mode, set_agent_mode
    from config.agent_mode import AGENT_MODE_READONLY

    _setup_repo(tmp_path, monkeypatch, audit=False)

    (tmp_path / "a.txt").write_text("a-old\n", encoding="utf-8")

    token = set_agent_mode(AGENT_MODE_READONLY)

    try:
        result = run_tool(
            "generate_unified_diff",
            {
                "changes": [
                    {"path": "a.txt", "new_content": "a-new\n"},
                ],
            },
        )

        assert "Unified diff 预览" in tool_result_message(result)
    finally:
        reset_agent_mode(token)


def test_batch_preview_failure_writes_failed_audit(tmp_path, monkeypatch):
    audit_file = _setup_repo(tmp_path, monkeypatch, audit=True)

    (tmp_path / "a.txt").write_text("a-old\n", encoding="utf-8")

    result = generate_unified_diff(
        changes=[
            {"path": "a.txt", "new_content": "a-new\n"},
            {"path": "../outside.txt", "new_content": "bad\n"},
        ],
    )

    assert "越界" in tool_result_message(result)

    event = json.loads(audit_file.read_text(encoding="utf-8").splitlines()[-1])

    assert event["status"] == "failed"
    assert event["file_count"] == 2
    assert event["failed_path"] == "../outside.txt"
