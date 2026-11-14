from schemas import FinishResponse, ToolCall, parse_agent_response


def test_plain_text():
    result = parse_agent_response("你好")
    assert isinstance(result, str)
    assert result == "你好"


def test_pure_json():
    result = parse_agent_response(
        '{"action":"calculator","args":{"a":1,"b":2}}'
    )
    assert isinstance(result, ToolCall)
    assert result.action == "calculator"


def test_mixed_text_and_json():
    mixed = (
        "我来分析当前项目结构，首先列出仓库中的工具类文件。\n"
        "{\n"
        '    "action": "analyze_repo_structure",\n'
        '    "args": {\n'
        '        "path": ".",\n'
        '        "max_depth": 3\n'
        "    }\n"
        "}"
    )
    result = parse_agent_response(mixed)
    assert isinstance(result, ToolCall)
    assert result.action == "analyze_repo_structure"


def test_markdown_json_block():
    markdown = (
        "说明如下：\n"
        "```json\n"
        '{"action": "finish", "answer": "完成"}\n'
        "```"
    )
    result = parse_agent_response(markdown)
    assert isinstance(result, FinishResponse)
    assert result.answer == "完成"


if __name__ == "__main__":
    test_plain_text()
    test_pure_json()
    test_mixed_text_and_json()
    test_markdown_json_block()
    print("all parse tests passed")
