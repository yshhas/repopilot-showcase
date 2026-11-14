"""Fixtures and gates for opt-in live LLM smoke eval."""

import os
import subprocess
from pathlib import Path
from typing import Any, Callable

import pytest

from config.agent_mode import AGENT_MODE_FULL, AGENT_MODE_READONLY

VALID_MODES = frozenset({"readonly", "full"})
CI_PLACEHOLDER_KEY = "ci-docker-smoke-placeholder"


def _live_auto_confirm(action, display_args):
    """Auto-approve mutation tools in opt-in live eval only."""

    _ = display_args
    return True


def live_llm_eval_enabled() -> bool:
    return os.getenv("LIVE_LLM_EVAL_ENABLED", "0").strip() == "1"


def has_live_llm_credentials() -> bool:
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    return bool(key) and key != CI_PLACEHOLDER_KEY


def _write_live_smoke_sample_repo(repo_root: Path) -> None:
    """Minimal in-repo files referenced by live smoke cases."""

    tools_dir = repo_root / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)

    (tools_dir / "tool_manager.py").write_text(
        '"""Minimal tool runner for live smoke sample repo."""\n\n\n'
        "def run_tool(name, args):\n"
        "    if not name:\n"
        "        raise ValueError('tool name required')\n"
        "    return 'ok'\n",
        encoding="utf-8",
    )

    (repo_root / "sample_agent.py").write_text(
        '"""Sample agent entrypoint for live smoke search cases."""\n\n'
        "from tools.tool_manager import run_tool\n\n\n"
        "def react_agent(task):\n"
        "    return run_tool('echo', {'task': task})\n",
        encoding="utf-8",
    )

    (repo_root / "sample.txt").write_text("original\n", encoding="utf-8")


def _init_git_repo(repo_root: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def live_smoke_git_repo(isolated_repo_paths):
    """Isolated git repo with files that live smoke cases expect."""

    repo_root = isolated_repo_paths
    _write_live_smoke_sample_repo(repo_root)
    _init_git_repo(repo_root)

    yield repo_root


@pytest.fixture(autouse=True)
def live_llm_gate(request):
    """Skip live_llm cases unless explicitly enabled with a real API key."""

    if request.node.get_closest_marker("live_llm") is None:
        return

    if not live_llm_eval_enabled():
        pytest.skip("LIVE_LLM_EVAL_ENABLED is not set to 1")

    if not has_live_llm_credentials():
        pytest.skip("DEEPSEEK_API_KEY is not set or is a CI placeholder")


@pytest.fixture
def live_run(
    live_smoke_git_repo,
    isolated_task_db,
    monkeypatch,
) -> Callable[[dict[str, Any], str | None], dict[str, Any]]:
    """Run one live smoke case against an isolated git repo with real ask_ai."""

    import config.settings as settings
    from react_agent import react_agent
    from storage.task_store import get_task

    from tests.live_llm.assertions import evaluate_live_case

    repo_root = live_smoke_git_repo

    monkeypatch.setattr(settings, "INDEX_ENABLED", False)
    monkeypatch.setattr(settings, "RAG_ENABLED", False)

    audit_file = settings.AUDIT_LOG_FILE

    def _run(case: dict[str, Any], task_id: str | None = None) -> dict[str, Any]:
        mode = case.get("mode", AGENT_MODE_READONLY)
        agent_mode = (
            AGENT_MODE_READONLY
            if mode == AGENT_MODE_READONLY
            else AGENT_MODE_FULL
        )
        resolved_task_id = task_id or ("live_" + case["id"])

        answer, memory = react_agent(
            case["question"],
            task_id=resolved_task_id,
            agent_mode=agent_mode,
            max_steps=case.get("max_steps", 12),
            confirm_callback=_live_auto_confirm,
        )

        task = get_task(resolved_task_id)

        evaluation = evaluate_live_case(
            case,
            task_id=resolved_task_id,
            task=task,
            audit_file=audit_file,
            repo_root=repo_root,
        )
        evaluation["answer"] = answer
        evaluation["memory"] = memory
        evaluation["task_id"] = resolved_task_id

        return evaluation

    return _run
