import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def test_requirements_file_exists():

    req = ROOT / "requirements.txt"

    assert req.exists()

    text = req.read_text(encoding="utf-8")

    assert "openai" in text

    assert "pydantic" in text

    assert "python-dotenv" in text

    assert "pytest" in text

    assert "fastapi" in text

    assert "uvicorn" in text


def test_readme_exists_and_covers_basics():

    readme = ROOT / "README.md"

    assert readme.exists()

    text = readme.read_text(encoding="utf-8")

    assert "react_agent.py" in text

    assert "api.main" in text

    assert "/tasks" in text

    assert "DEEPSEEK_API_KEY" in text

    assert "git_create_backup" in text

    assert "write_repo_file" in text

    assert "generate_unified_diff" in text

    assert "apply_patch" in text

    assert "audit.jsonl" in text

    assert "task_report" in text

    assert "tasks.db" in text

    assert "docs/architecture.md" in text

    assert "docs/workflow.md" in text

    assert "docs/demo.md" in text

    assert "docs/GITHUB_DEMO.md" in text

    assert "docs/testing_live_llm_eval.md" in text

    assert (ROOT / "LICENSE").exists()

    assert (ROOT / "CHANGELOG.md").exists()

    assert "v0.10.2" in text

    assert "verify_change" in text

    assert "AGENT_MODE" in text

    assert "docs/DEMO_RECORDING.md" in text

    assert "docs/assets/" in text

    assert ".env.example" in text


def test_env_example_exists():

    example = ROOT / ".env.example"

    assert example.exists()

    text = example.read_text(encoding="utf-8")

    assert "DEEPSEEK_API_KEY" in text

    assert "EXECUTION_STATE_DEDUP_ENABLED" in text

    assert "MUTATION_FSM_ENABLED" in text

    assert "STRUCTURED_TOOL_REJECT_ENABLED" in text


def test_demo_assets_structure_exists():

    assets_dir = ROOT / "docs" / "assets"

    assert assets_dir.is_dir()

    assert (assets_dir / "README.md").exists()

    assert (ROOT / "docs" / "DEMO_RECORDING.md").exists()

    # If README embeds docs/assets/* media, those files must be committed.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    names = re.findall(
        r"docs/assets/([\w.-]+\.(?:png|gif|jpg|jpeg|webp))",
        readme,
        flags=re.IGNORECASE,
    )

    for name in names:
        assert (assets_dir / name).exists(), "missing demo asset: " + name


def test_security_policy_reflects_current_release():

    security = ROOT / "SECURITY.md"

    assert security.exists()

    text = security.read_text(encoding="utf-8")

    assert "v0.10.2" in text

    assert "(Unreleased)" not in text

    assert "apply_patch" in text

    assert "generate_unified_diff" in text

    assert "verify_change" in text or "Verification" in text


def test_workflow_doc_reflects_diff_tools():

    workflow = ROOT / "docs" / "workflow.md"

    text = workflow.read_text(encoding="utf-8")

    assert "generate_unified_diff" in text

    assert "apply_patch" in text

    assert "Unreleased" not in text


def test_architecture_doc_reflects_v0_10():

    architecture = ROOT / "docs" / "architecture.md"

    text = architecture.read_text(encoding="utf-8")

    assert "v0.10.2" in text

    assert "v0.7.0（RC 就绪）" not in text

    assert "/tasks/{task_id}/cancel" in text

    assert "/tasks/{task_id}/resume" in text

    assert "context/tms" in text

    assert "313+" not in text

    assert "525" in text

    assert "verify_change" in text


def test_workflow_doc_reflects_v0_10():

    workflow = ROOT / "docs" / "workflow.md"

    text = workflow.read_text(encoding="utf-8")

    assert "v0.10.2" in text

    assert "v0.4.0（已 release）" not in text

    assert "cancel" in text.lower()

    assert "resume" in text.lower()


def test_github_demo_uses_test_txt():

    github_demo = ROOT / "docs" / "GITHUB_DEMO.md"

    text = github_demo.read_text(encoding="utf-8")

    assert "test.txt" in text

    assert "sample.txt" not in text
