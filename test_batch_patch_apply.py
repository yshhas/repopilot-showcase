import json
import subprocess

import pytest

from audit.context import (
    reset_agent_mode,
    reset_skip_tool_confirm,
    set_agent_mode,
    set_skip_tool_confirm,
)
from config.agent_mode import AGENT_MODE_READONLY
from tools.git_tools import git_create_backup
from tools.patch_apply import apply_patch, apply_repo_patch, apply_repo_patch_batch
from schemas import FileChange
from tools.result_schema import tool_result_message
from tools.tool_manager import run_tool


@pytest.fixture(autouse=True)
def _disable_fsm_for_batch_patch_unit_tests(disable_mutation_fsm):
    return disable_mutation_fsm


def _write_files(repo_root, files: dict[str, str]):
    for path, content in files.items():
        (repo_root / path).write_text(content, encoding="utf-8")


def _git_add_commit(repo_root, message: str = "add batch files"):
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )


def test_apply_repo_patch_batch_three_files_success(isolated_git_repo):
    git_create_backup()

    _write_files(
        isolated_git_repo,
        {
            "a.txt": "a-old\n",
            "b.txt": "b-old\n",
            "c.txt": "c-old\n",
        },
    )

    result = apply_repo_patch_batch(
        [
            FileChange(path="a.txt", new_content="a-new\n"),
            FileChange(path="b.txt", new_content="b-new\n"),
            FileChange(path="c.txt", new_content="c-new\n"),
        ],
    )

    assert "Patch 批量应用完成" in tool_result_message(result)
    assert "文件数: 3" in tool_result_message(result)
    assert isolated_git_repo.joinpath("a.txt").read_text(encoding="utf-8") == "a-new\n"
    assert isolated_git_repo.joinpath("b.txt").read_text(encoding="utf-8") == "b-new\n"
    assert isolated_git_repo.joinpath("c.txt").read_text(encoding="utf-8") == "c-new\n"


def test_apply_patch_batch_via_run_tool(isolated_git_repo):
    git_create_backup()
    confirm_token = set_skip_tool_confirm(True)

    _write_files(
        isolated_git_repo,
        {
            "a.txt": "a-old\n",
            "b.txt": "b-old\n",
            "c.txt": "c-old\n",
        },
    )

    try:
        result = run_tool(
            "apply_patch",
            {
                "changes": [
                    {"path": "a.txt", "new_content": "a-new\n"},
                    {"path": "b.txt", "new_content": "b-new\n"},
                    {"path": "c.txt", "new_content": "c-new\n"},
                ],
            },
        )

        assert "Patch 批量应用完成" in tool_result_message(result)
        assert isolated_git_repo.joinpath("c.txt").read_text(encoding="utf-8") == "c-new\n"
    finally:
        reset_skip_tool_confirm(confirm_token)


def test_apply_repo_patch_batch_check_fail_leaves_files_unchanged(
    isolated_git_repo,
    monkeypatch,
):
    git_create_backup()

    _write_files(
        isolated_git_repo,
        {
            "a.txt": "a-old\n",
            "b.txt": "b-old\n",
            "c.txt": "c-old\n",
        },
    )

    import tools.patch_apply as patch_apply_module

    original_run_git = patch_apply_module._run_git

    def fake_run_git(args, *, input_text=None):
        if args == ["apply", "--check", "-"]:
            return False, "simulated batch check failure"

        return original_run_git(args, input_text=input_text)

    monkeypatch.setattr(patch_apply_module, "_run_git", fake_run_git)

    result = apply_repo_patch_batch(
        [
            FileChange(path="a.txt", new_content="a-new\n"),
            FileChange(path="b.txt", new_content="b-new\n"),
            FileChange(path="c.txt", new_content="c-new\n"),
        ],
    )

    assert "预检失败" in tool_result_message(result)
    assert isolated_git_repo.joinpath("a.txt").read_text(encoding="utf-8") == "a-old\n"
    assert isolated_git_repo.joinpath("b.txt").read_text(encoding="utf-8") == "b-old\n"
    assert isolated_git_repo.joinpath("c.txt").read_text(encoding="utf-8") == "c-old\n"


def test_apply_patch_batch_rejects_without_backup(isolated_git_repo):
    _write_files(
        isolated_git_repo,
        {
            "a.txt": "a-old\n",
            "b.txt": "b-old\n",
        },
    )

    result = apply_patch(
        changes=[
            {"path": "a.txt", "new_content": "a-new\n"},
            {"path": "b.txt", "new_content": "b-new\n"},
        ],
    )

    assert "备份" in tool_result_message(result)
    assert isolated_git_repo.joinpath("a.txt").read_text(encoding="utf-8") == "a-old\n"
    assert isolated_git_repo.joinpath("b.txt").read_text(encoding="utf-8") == "b-old\n"


def test_run_tool_apply_patch_batch_blocked_in_readonly_mode(isolated_git_repo):
    _write_files(isolated_git_repo, {"a.txt": "a-old\n"})

    token = set_agent_mode(AGENT_MODE_READONLY)

    try:
        result = run_tool(
            "apply_patch",
            {
                "changes": [
                    {"path": "a.txt", "new_content": "a-new\n"},
                ],
            },
        )

        assert "readonly" in tool_result_message(result)
        assert "apply_patch" in tool_result_message(result)
        assert isolated_git_repo.joinpath("a.txt").read_text(encoding="utf-8") == "a-old\n"
    finally:
        reset_agent_mode(token)


def test_run_tool_apply_patch_batch_confirm_cancel(isolated_git_repo, monkeypatch):
    git_create_backup()
    _write_files(isolated_git_repo, {"a.txt": "a-old\n", "b.txt": "b-old\n"})

    monkeypatch.setattr(
        "tools.tool_manager.request_tool_confirmation",
        lambda action, args, confirm_callback=None: False,
    )

    result = run_tool(
        "apply_patch",
        {
            "changes": [
                {"path": "a.txt", "new_content": "a-new\n"},
                {"path": "b.txt", "new_content": "b-new\n"},
            ],
        },
    )

    assert tool_result_message(result) == "用户已取消执行工具: apply_patch"
    assert isolated_git_repo.joinpath("a.txt").read_text(encoding="utf-8") == "a-old\n"


def test_apply_patch_changes_one_matches_legacy(isolated_git_repo):
    git_create_backup()

    legacy = apply_patch(path="sample.txt", new_content="legacy-updated\n")
    isolated_git_repo.joinpath("sample.txt").write_text("original\n", encoding="utf-8")

    batch_one = apply_patch(
        changes=[{"path": "sample.txt", "new_content": "batch-one-updated\n"}],
    )

    assert "Patch 应用完成" in tool_result_message(legacy)
    assert "Patch 应用完成" in tool_result_message(batch_one)
    assert (
        isolated_git_repo.joinpath("sample.txt").read_text(encoding="utf-8")
        == "batch-one-updated\n"
    )


def test_apply_patch_batch_writes_batch_audit_fields(isolated_git_repo):
    git_create_backup()

    audit_file = isolated_git_repo / "audit.jsonl"

    _write_files(
        isolated_git_repo,
        {
            "a.txt": "a-old\n",
            "b.txt": "b-old\n",
        },
    )

    apply_repo_patch_batch(
        [
            FileChange(path="a.txt", new_content="a-new\n"),
            FileChange(path="b.txt", new_content="b-new\n"),
        ],
    )

    event = json.loads(audit_file.read_text(encoding="utf-8").splitlines()[-1])

    assert event["event"] == "patch_apply"
    assert event["status"] == "success"
    assert event["file_count"] == 2
    assert "a.txt" in event["paths"]
    assert "b.txt" in event["paths"]
    assert "bytes" not in event
    assert "created" not in event
    assert "new_content" not in event
    assert "--- a/" not in json.dumps(event)


def test_apply_patch_single_file_audit_keeps_v04_shape(isolated_git_repo):
    git_create_backup()

    audit_file = isolated_git_repo / "audit.jsonl"

    apply_repo_patch("sample.txt", "updated\n")

    event = json.loads(audit_file.read_text(encoding="utf-8").splitlines()[-1])

    assert event["path"] == "sample.txt"
    assert event["status"] == "success"
    assert "bytes" in event
    assert "created" in event
    assert "file_count" not in event
    assert "paths" not in event


def test_apply_patch_batch_validation_fail_before_git(isolated_git_repo):
    git_create_backup()
    audit_file = isolated_git_repo / "audit.jsonl"

    _write_files(isolated_git_repo, {"good.txt": "good\n"})

    result = apply_repo_patch_batch(
        [
            FileChange(path="good.txt", new_content="good-new\n"),
            FileChange(path="../outside.txt", new_content="bad\n"),
        ],
    )

    assert "越界" in tool_result_message(result)
    assert isolated_git_repo.joinpath("good.txt").read_text(encoding="utf-8") == "good\n"

    event = json.loads(audit_file.read_text(encoding="utf-8").splitlines()[-1])

    assert event["status"] == "failed"
    assert event["file_count"] == 2
    assert event["failed_path"] == "../outside.txt"


def test_apply_patch_batch_uses_single_git_apply(isolated_git_repo, monkeypatch):
    git_create_backup()

    _write_files(
        isolated_git_repo,
        {
            "a.txt": "a-old\n",
            "b.txt": "b-old\n",
            "c.txt": "c-old\n",
        },
    )

    import tools.patch_apply as patch_apply_module

    calls: list[list[str]] = []

    original_run_git = patch_apply_module._run_git

    def tracking_run_git(args, *, input_text=None):
        calls.append(list(args))
        return original_run_git(args, input_text=input_text)

    monkeypatch.setattr(patch_apply_module, "_run_git", tracking_run_git)

    apply_repo_patch_batch(
        [
            FileChange(path="a.txt", new_content="a-new\n"),
            FileChange(path="b.txt", new_content="b-new\n"),
            FileChange(path="c.txt", new_content="c-new\n"),
        ],
    )

    check_calls = [args for args in calls if args == ["apply", "--check", "-"]]
    apply_calls = [args for args in calls if args == ["apply", "-"]]

    assert len(check_calls) == 1
    assert len(apply_calls) == 1


def test_tool_confirm_formats_batch_changes_summary():
    from security.tool_confirm import _format_confirm_args

    display = _format_confirm_args(
        "apply_patch",
        {
            "changes": [
                {"path": "a.txt", "new_content": "a\n"},
                {"path": "b.txt", "new_content": "x" * 300},
            ],
        },
    )

    assert "files(2)" in display["changes"]
    assert "a.txt" in display["changes"]
    assert "b.txt" in display["changes"]
    assert "...[truncated]" in display["changes"]
