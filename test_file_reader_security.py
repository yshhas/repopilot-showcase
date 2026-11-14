from tools.file_reader import read_file
from tools.repo_reader import read_repo_file
from tools.tool_manager import TOOLS, get_react_tools


def _setup_repo(tmp_path, monkeypatch):

    monkeypatch.setenv("REPO_ROOT", str(tmp_path))

    import config.settings as settings

    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)

    import context.project_context as project_context_module

    monkeypatch.setattr(project_context_module, "REPO_ROOT", tmp_path)

    import security.path_guard as path_guard

    monkeypatch.setattr(path_guard, "REPO_ROOT", tmp_path)

    sample = tmp_path / "sample.txt"

    sample.write_text("hello repo\n", encoding="utf-8")

    env_file = tmp_path / ".env"

    env_file.write_text("SECRET=1\n", encoding="utf-8")


def test_file_reader_not_exposed_to_react():

    react_tools = get_react_tools()

    assert "file_reader" not in react_tools

    assert "read_repo_file" in react_tools


def test_file_reader_tool_registered_for_legacy_use():

    assert "file_reader" in TOOLS

    assert TOOLS["file_reader"]["react"] is False


def test_read_file_delegates_with_repo_security(tmp_path, monkeypatch):

    _setup_repo(tmp_path, monkeypatch)

    result = read_file("sample.txt")

    assert "hello repo" in result


def test_read_file_rejects_env_via_repo_security(tmp_path, monkeypatch):

    _setup_repo(tmp_path, monkeypatch)

    result = read_file(".env")

    assert "拒绝访问敏感文件" in result


def test_read_file_rejects_outside_repo_absolute_path(tmp_path, monkeypatch):

    _setup_repo(tmp_path, monkeypatch)

    outside = tmp_path.parent / "outside.txt"

    outside.write_text("outside\n", encoding="utf-8")

    result = read_file(str(outside))

    assert "拒绝访问" in result


def test_read_file_accepts_absolute_path_under_repo(tmp_path, monkeypatch):

    _setup_repo(tmp_path, monkeypatch)

    sample = tmp_path / "sample.txt"

    result = read_file(str(sample))

    assert "hello repo" in result


def test_read_repo_file_still_works(tmp_path, monkeypatch):

    _setup_repo(tmp_path, monkeypatch)

    result = read_repo_file("sample.txt")

    assert "hello repo" in result


def test_read_repo_file_rejects_env(tmp_path, monkeypatch):

    _setup_repo(tmp_path, monkeypatch)

    result = read_repo_file(".env")

    assert "拒绝访问敏感文件" in result


def test_read_repo_file_redacts_secrets_in_allowed_file(tmp_path, monkeypatch):

    _setup_repo(tmp_path, monkeypatch)

    config_file = tmp_path / "config.py"

    config_file.write_text(
        "DEEPSEEK_API_KEY=sk-test-secret-value-12345\n"
        "APP_NAME = demo\n",
        encoding="utf-8",
    )

    result = read_repo_file("config.py")

    assert "sk-test-secret-value" not in result

    assert "[REDACTED]" in result

    assert "APP_NAME = demo" in result


def test_search_in_repo_redacts_match_lines(tmp_path, monkeypatch):

    _setup_repo(tmp_path, monkeypatch)

    config_file = tmp_path / "settings.txt"

    config_file.write_text(
        "api_key = super-long-secret-value\n"
        "public info\n",
        encoding="utf-8",
    )

    from tools.repo_reader import search_in_repo

    result = search_in_repo("api_key", extensions=".txt")

    assert "super-long-secret-value" not in result

    assert "[REDACTED]" in result

    assert "public info" not in result or "public" in result
