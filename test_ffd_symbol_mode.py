from index.builder import build_index
from tools.repo_analyzer import find_file_dependencies
from tools.result_schema import tool_result_message
from tools.tool_manager import run_tool


def test_ffd_symbol_mode_returns_definition_and_reference(isolated_index_repo):
    build_index(isolated_index_repo, force=True)

    result = find_file_dependencies(
        symbol="FileChange",
        query_mode="symbol",
        max_results=20,
    )

    assert "Symbol 查询: FileChange" in tool_result_message(result)
    assert "===== 定义 (definition) =====" in tool_result_message(result)
    assert "===== 引用 (reference) =====" in tool_result_message(result)
    assert "models.py:" in tool_result_message(result)
    assert "consumer.py:" in tool_result_message(result)


def test_ffd_symbol_via_run_tool(isolated_index_repo):
    build_index(isolated_index_repo, force=True)

    result = run_tool(
        "find_file_dependencies",
        {"symbol": "FileChange", "query_mode": "symbol"},
    )

    assert "Symbol 查询: FileChange" in tool_result_message(result)


def test_ffd_auto_mode_prefers_symbol(isolated_index_repo):
    build_index(isolated_index_repo, force=True)

    result = find_file_dependencies(
        path="consumer.py",
        symbol="FileChange",
        query_mode="auto",
    )

    assert "Symbol 查询: FileChange" in tool_result_message(result)
