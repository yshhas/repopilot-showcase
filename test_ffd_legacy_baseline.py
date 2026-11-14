import config.settings as settings
from tools.result_schema import tool_result_message
from tools.repo_analyzer import find_file_dependencies


def test_ffd_legacy_dependencies_output_snapshot(isolated_index_repo, monkeypatch):
    monkeypatch.setattr(settings, "INDEX_ENABLED", False)

    result = find_file_dependencies(
        path="consumer.py",
        max_results=100,
        query_mode="dependencies",
    )

    assert result == (
        "项目: "
        + isolated_index_repo.name
        + "\n文件: consumer.py\n\n"
        "===== 本文件 import =====\n"
        "models\n\n"
        "===== 可能依赖本文件的模块 =====\n"
        "(未发现其他文件直接 import 该模块)\n\n"
        "说明: 依赖分析基于 import 语句，属于基础静态分析。"
    )


def test_ffd_legacy_auto_mode_with_path_only(isolated_index_repo, monkeypatch):
    monkeypatch.setattr(settings, "INDEX_ENABLED", False)

    explicit = find_file_dependencies(path="consumer.py", query_mode="dependencies")
    auto = find_file_dependencies(path="consumer.py")

    assert auto == explicit


def test_ffd_run_tool_legacy_unchanged(isolated_index_repo, monkeypatch):
    monkeypatch.setattr(settings, "INDEX_ENABLED", False)

    from tools.tool_manager import run_tool

    result = run_tool(
        "find_file_dependencies",
        {"path": "consumer.py", "max_results": 100},
    )

    assert "===== 本文件 import =====" in tool_result_message(result)
    assert "models" in tool_result_message(result)
    assert "Symbol 查询" not in tool_result_message(result)
