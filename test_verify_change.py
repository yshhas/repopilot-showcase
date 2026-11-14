"""v0.10.2 verify_change unit + lifecycle tests."""

import json

import config.settings as settings
from audit.context import reset_agent_mode, set_agent_mode
from config.agent_mode import AGENT_MODE_FULL, AGENT_MODE_READONLY
from context.tms import (
    VerificationStatus,
    export_mutation_state_for_checkpoint,
    get_mutation_state,
    hydrate_mutation_state_v1,
    reset_mutation_state,
)
from context.tms.types import MutationPath, MutationWorkflowState
from tools.outcome_schema import is_tool_success
from tools.result_schema import is_tool_reject
from tools.tool_manager import get_react_tools, run_tool


def _seed_patched(paths: list[str]):
    reset_mutation_state()
    state = get_mutation_state()
    state.workflow.state = MutationWorkflowState.PATCHED
    state.workflow.path = MutationPath.DIFF_FIRST
    state.artifacts.patch_applied = True
    state.artifacts.patch_applied_paths = list(paths)


def test_react_tool_count_includes_verify_change():
    assert len(get_react_tools(AGENT_MODE_FULL)) == 15
    assert "verify_change" in get_react_tools(AGENT_MODE_FULL)
    assert "verify_change" not in get_react_tools(AGENT_MODE_READONLY)


def test_verify_change_blocked_before_patched(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", tmp_path / "audit.jsonl")
    (tmp_path / "sample.py").write_text("x = 1\n", encoding="utf-8")
    reset_mutation_state()
    mode_token = set_agent_mode(AGENT_MODE_FULL)
    try:
        result = run_tool("verify_change", {})
    finally:
        reset_agent_mode(mode_token)

    assert is_tool_reject(result)
    assert result["code"] == "mutation_fsm_blocked"


def test_verify_change_passes_after_patch(isolated_repo_paths, monkeypatch):
    repo = isolated_repo_paths
    (repo / "sample.py").write_text("x = 2\n", encoding="utf-8")
    _seed_patched(["sample.py"])

    mode_token = set_agent_mode(AGENT_MODE_FULL)
    try:
        result = run_tool("verify_change", {})
    finally:
        reset_agent_mode(mode_token)

    assert is_tool_success(result)
    assert result["code"] == "verify_passed"
    state = get_mutation_state()
    assert state.workflow.state == MutationWorkflowState.PATCHED
    assert state.verification.status == VerificationStatus.PASSED


def test_verify_change_fails_on_syntax_error(isolated_repo_paths, monkeypatch):
    repo = isolated_repo_paths
    (repo / "sample.py").write_text("def broken(\n", encoding="utf-8")
    _seed_patched(["sample.py"])

    mode_token = set_agent_mode(AGENT_MODE_FULL)
    try:
        result = run_tool(
            "verify_change",
            {"checks": "syntax", "paths": "sample.py"},
        )
    finally:
        reset_agent_mode(mode_token)

    assert is_tool_success(result)
    assert result["code"] == "verify_failed"
    assert get_mutation_state().workflow.state == MutationWorkflowState.PATCHED
    assert get_mutation_state().verification.status == VerificationStatus.FAILED


def test_verify_change_fails_on_missing_file(isolated_repo_paths, monkeypatch):
    _seed_patched(["missing_after_patch.py"])

    mode_token = set_agent_mode(AGENT_MODE_FULL)
    try:
        result = run_tool(
            "verify_change",
            {"checks": "patched_files", "paths": "missing_after_patch.py"},
        )
    finally:
        reset_agent_mode(mode_token)

    assert result["code"] == "verify_failed"
    assert "missing" in result["message"].lower() or "missing" in str(
        result["details"].get("failures", [])
    ).lower()


def test_verify_change_skipped_without_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", tmp_path / "audit.jsonl")
    _seed_patched([])

    mode_token = set_agent_mode(AGENT_MODE_FULL)
    try:
        result = run_tool("verify_change", {})
    finally:
        reset_agent_mode(mode_token)

    assert result["code"] == "verify_skipped"
    assert get_mutation_state().verification.status == VerificationStatus.SKIPPED


def test_verification_slice_checkpoint_roundtrip(isolated_repo_paths, monkeypatch):
    (isolated_repo_paths / "sample.py").write_text("x = 1\n", encoding="utf-8")
    _seed_patched(["sample.py"])
    mode_token = set_agent_mode(AGENT_MODE_FULL)
    try:
        run_tool("verify_change", {})
    finally:
        reset_agent_mode(mode_token)

    blob = export_mutation_state_for_checkpoint()
    assert blob["verification"]["status"] == "PASSED"
    assert blob["verification"]["last_code"] == "verify_passed"

    restored = hydrate_mutation_state_v1(blob)
    assert restored.verification.status == VerificationStatus.PASSED
    assert restored.workflow.state == MutationWorkflowState.PATCHED


def test_verify_change_writes_audit_event(isolated_repo_paths, monkeypatch):
    (isolated_repo_paths / "sample.py").write_text("x = 1\n", encoding="utf-8")
    _seed_patched(["sample.py"])
    audit_file = settings.AUDIT_LOG_FILE
    mode_token = set_agent_mode(AGENT_MODE_FULL)
    try:
        run_tool("verify_change", {})
    finally:
        reset_agent_mode(mode_token)

    events = [
        json.loads(line)
        for line in audit_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    verify_events = [e for e in events if e.get("event") == "verify_change_result"]
    assert len(verify_events) >= 1
    assert verify_events[-1]["status"] == "passed"


def test_verify_change_blocked_in_readonly(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)
    mode_token = set_agent_mode(AGENT_MODE_READONLY)
    try:
        result = run_tool("verify_change", {})
    finally:
        reset_agent_mode(mode_token)

    assert is_tool_reject(result)
    assert result["code"] == "tool_not_allowed"
