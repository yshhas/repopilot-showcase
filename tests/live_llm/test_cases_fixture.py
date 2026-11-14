import json
from pathlib import Path

from tests.live_llm.conftest import VALID_MODES


def test_live_llm_cases_fixture_schema():
    fixture = Path(__file__).resolve().parent / "cases.json"
    cases = json.loads(fixture.read_text(encoding="utf-8"))

    assert isinstance(cases, list)
    assert len(cases) >= 1

    seen_ids = set()

    for item in cases:
        assert "id" in item
        assert item["id"] not in seen_ids
        seen_ids.add(item["id"])

        assert item.get("mode") in VALID_MODES
        assert isinstance(item.get("question"), str)
        assert item["question"].strip()

        max_steps = item.get("max_steps", 12)
        assert isinstance(max_steps, int)
        assert 1 <= max_steps <= 30

        if "require_tools_any" in item:
            tools = item["require_tools_any"]
            assert isinstance(tools, list)
            assert tools
            assert all(isinstance(name, str) and name for name in tools)

        if "forbid_mutation_tools" in item:
            assert isinstance(item["forbid_mutation_tools"], bool)

        if "require_tool_confirmation" in item:
            tools = item["require_tool_confirmation"]
            assert isinstance(tools, list)
            assert tools
            assert all(isinstance(name, str) and name for name in tools)

        if "assert_file_contains" in item:
            spec = item["assert_file_contains"]
            assert isinstance(spec, dict)
            assert isinstance(spec.get("path"), str) and spec["path"].strip()
            assert isinstance(spec.get("substring"), str) and spec["substring"]

        if "require_task_completed" in item:
            assert isinstance(item["require_task_completed"], bool)
