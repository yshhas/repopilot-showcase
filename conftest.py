"""Pytest configuration and shared test fixtures."""

import subprocess
from typing import Any

import pytest

collect_ignore = []


def tool_result_text(result: Any) -> str:
    """Display/message text for plain str or structured tool outcomes (PR-M2)."""
    from tools.result_schema import tool_result_message

    return tool_result_message(result)


@pytest.fixture
def disable_mutation_fsm(monkeypatch):
    """Opt out of default-on FSM for tool-unit tests that bypass workflow order."""
    import config.settings as settings

    monkeypatch.setattr(settings, "MUTATION_FSM_ENABLED", False)


@pytest.fixture
def disable_structured_tool_reject(monkeypatch):
    """Opt out of default-on structured reject (string-only reject messages)."""
    import config.settings as settings

    monkeypatch.setattr(settings, "STRUCTURED_TOOL_REJECT_ENABLED", False)


def _reset_project_context_backup_state(project_context_module):
    project_context_module._last_backup_branch = None
    project_context_module._last_backup_commit = None
    project_context_module._last_original_branch = None


def _patch_isolated_repo_paths(tmp_path, monkeypatch):
    """Redirect repo/audit/backup paths to tmp_path across imported modules."""

    audit_file = tmp_path / "audit.jsonl"
    backup_file = tmp_path / "last_backup.json"

    monkeypatch.setenv("REPO_ROOT", str(tmp_path))

    import config.settings as settings

    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", audit_file)
    monkeypatch.setattr(settings, "BACKUP_STATE_FILE", backup_file)

    import context.project_context as project_context_module

    monkeypatch.setattr(project_context_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(project_context_module, "BACKUP_STATE_FILE", backup_file)
    _reset_project_context_backup_state(project_context_module)

    import security.path_guard as path_guard

    monkeypatch.setattr(path_guard, "REPO_ROOT", tmp_path)

    import tools.git_tools as git_tools_module

    monkeypatch.setattr(git_tools_module, "REPO_ROOT", tmp_path)

    import audit.audit_log as audit_log_module

    monkeypatch.setattr(audit_log_module, "AUDIT_LOG_FILE", audit_file)

    if backup_file.exists():
        backup_file.unlink()

    if audit_file.exists():
        audit_file.unlink()

    from context.execution_state import reset_execution_state
    from context.tms import reset_mutation_state

    reset_execution_state()
    reset_mutation_state()

    return {
        "repo_root": tmp_path,
        "audit_file": audit_file,
        "backup_file": backup_file,
    }


def _patch_isolated_task_db(tmp_path, monkeypatch):
    """Redirect SQLite task store to tmp_path (module-level TASK_DB_FILE bindings)."""

    db_file = tmp_path / "tasks.db"

    import config.settings as settings

    import storage.task_store as task_store_module

    monkeypatch.setattr(settings, "TASK_DB_FILE", db_file)
    monkeypatch.setattr(task_store_module, "TASK_DB_FILE", db_file)

    if db_file.exists():
        db_file.unlink()

    return db_file


def _patch_isolated_index_paths(tmp_path, monkeypatch, *, enabled=True):
    """Redirect repo index DB under tmp_path; opt-in INDEX_ENABLED per test."""

    index_db = tmp_path / "database" / "repo_index.db"

    import config.settings as settings

    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "INDEX_DB_FILE", index_db)
    monkeypatch.setattr(settings, "INDEX_ENABLED", enabled)
    monkeypatch.setattr(settings, "INDEX_AUTO_REBUILD", True)

    import context.project_context as project_context_module
    import security.path_guard as path_guard

    monkeypatch.setattr(project_context_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(path_guard, "REPO_ROOT", tmp_path)

    if index_db.exists():
        index_db.unlink()

    return index_db


def _write_index_sample_repo(repo_root):
    models = repo_root / "models.py"
    models.write_text(
        "class FileChange:\n"
        "    def validate(self):\n"
        "        return True\n",
        encoding="utf-8",
    )

    consumer = repo_root / "consumer.py"
    consumer.write_text(
        "from models import FileChange\n\n\n"
        "def build_change():\n"
        "    return FileChange()\n",
        encoding="utf-8",
    )

    bad = repo_root / "bad_syntax.py"
    bad.write_text("def oops(\n", encoding="utf-8")


@pytest.fixture
def isolated_index_repo(tmp_path, monkeypatch):
    """Git repo under tmp_path with index paths isolated and INDEX_ENABLED=True."""

    _patch_isolated_index_paths(tmp_path, monkeypatch, enabled=True)
    _write_index_sample_repo(tmp_path)
    _init_git_repo(tmp_path)
    yield tmp_path


@pytest.fixture
def isolated_index_repo_no_git(tmp_path, monkeypatch):
    _patch_isolated_index_paths(tmp_path, monkeypatch, enabled=True)
    _write_index_sample_repo(tmp_path)
    yield tmp_path


def _patch_isolated_rag_paths(tmp_path, monkeypatch, *, enabled=True):
    """Redirect RAG vector store under tmp_path; opt-in RAG_ENABLED per test."""

    rag_dir = tmp_path / "database" / "rag_vectors"

    import config.settings as settings

    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "RAG_VECTOR_DIR", rag_dir)
    monkeypatch.setattr(settings, "RAG_ENABLED", enabled)
    monkeypatch.setattr(settings, "RAG_AUTO_REBUILD", True)
    monkeypatch.setattr(settings, "RAG_EMBEDDING_MODEL", "mock-deterministic-v1")

    import context.project_context as project_context_module
    import security.path_guard as path_guard

    monkeypatch.setattr(project_context_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(path_guard, "REPO_ROOT", tmp_path)

    if rag_dir.exists():
        import shutil

        shutil.rmtree(rag_dir, ignore_errors=True)

    return rag_dir


def _write_rag_sample_repo(repo_root):
    models = repo_root / "models.py"
    models.write_text(
        "class FileChange:\n"
        "    def validate(self):\n"
        "        return True\n\n\n"
        "def build_change():\n"
        "    return FileChange()\n",
        encoding="utf-8",
    )

    readme = repo_root / "README.md"
    readme.write_text(
        "# Sample\n\n"
        "Context budget truncation for large repositories.\n",
        encoding="utf-8",
    )


@pytest.fixture
def isolated_rag_repo(tmp_path, monkeypatch):
    """Git repo under tmp_path with RAG paths isolated and RAG_ENABLED=True."""

    _patch_isolated_rag_paths(tmp_path, monkeypatch, enabled=True)
    _write_rag_sample_repo(tmp_path)
    _init_git_repo(tmp_path, sample_name=None, sample_content="")
    yield tmp_path


@pytest.fixture
def isolated_rag_repo_no_git(tmp_path, monkeypatch):
    _patch_isolated_rag_paths(tmp_path, monkeypatch, enabled=True)
    _write_rag_sample_repo(tmp_path)
    yield tmp_path


def _init_git_repo(repo_root, *, sample_name="sample.txt", sample_content="original\n"):
    if sample_name and not (repo_root / sample_name).exists():
        sample = repo_root / sample_name
        sample.write_text(sample_content, encoding="utf-8")

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

    # Reset stale backup globals from previous isolated test repos
    from context.project_context import _reset_backup_global_state
    _reset_backup_global_state()


@pytest.fixture
def isolated_repo_paths(tmp_path, monkeypatch):
    """Isolate REPO_ROOT, audit JSONL, and backup state under tmp_path.

    Use for read/diff/patch tests that must not write to project logs/ or database/.
    Does not initialize Git; pair with isolated_git_repo when git tools are needed.
    """

    paths = _patch_isolated_repo_paths(tmp_path, monkeypatch)
    yield paths["repo_root"]


@pytest.fixture
def isolated_git_repo(isolated_repo_paths):
    """isolated_repo_paths plus git init, baseline commit, and sample.txt.

    sample.txt (content: \"original\\n\") matches existing patch tool tests.
    Tests may overwrite or add files after fixture setup.
    """

    repo_root = isolated_repo_paths
    _init_git_repo(repo_root)
    yield repo_root


@pytest.fixture
def isolated_task_db(tmp_path, monkeypatch):
    """Isolate SQLite task persistence under tmp_path/tasks.db.

    Use when react_agent or API flows write tasks and assertions need get_task().
    Not autouse — opt in per golden/integration test.
    """

    yield _patch_isolated_task_db(tmp_path, monkeypatch)


@pytest.fixture
def mock_ask_ai_sequence(monkeypatch):
    """Install sequential fake LLM outputs on react_agent.ask_ai (golden Mode A/B).

    Usage in test:

        mock_ask_ai_sequence.install([
            '{\"action\": \"git_status\", \"args\": {}}',
            '{\"action\": \"finish\", \"answer\": \"done\"}',
        ])

    Tracks call count in [\"count\"]; raises if ask_ai is invoked more than configured.
    """

    state: dict[str, Any] = {"count": 0, "responses": []}

    def install(responses: list[str]):
        state["responses"] = list(responses)
        state["count"] = 0

        def fake_ask_ai(memory, agent_mode=None):
            index = state["count"]

            if index >= len(state["responses"]):
                raise AssertionError(
                    "ask_ai called "
                    + str(index + 1)
                    + " times but only "
                    + str(len(state["responses"]))
                    + " responses configured"
                )

            state["count"] = index + 1

            return state["responses"][index]

        monkeypatch.setattr("react_agent.ask_ai", fake_ask_ai)

    state["install"] = install

    yield state


@pytest.fixture
def tool_call_spy(monkeypatch):
    """Spy react_agent.run_tool for golden orchestration assertions (Mode A).

    Usage in test:

        tool_call_spy.install()
        react_agent(...)
        assert [c[\"action\"] for c in tool_call_spy[\"calls\"]] == [...]

    Default stub returns a short success string without executing real tools.
    Pass use_real_run_tool=True to skip patching (Mode B).
    """

    state: dict[str, Any] = {"calls": []}

    def install(*, stub_prefix="[golden stub]", use_real_run_tool=False):
        state["calls"].clear()

        if use_real_run_tool:
            return

        def spy_run_tool(action, args):
            state["calls"].append(
                {
                    "action": action,
                    "args": dict(args) if args else {},
                }
            )

            return stub_prefix + " " + action + " ok"

        monkeypatch.setattr("react_agent.run_tool", spy_run_tool)

    state["install"] = install

    yield state
