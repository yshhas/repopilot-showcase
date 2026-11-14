import json
from pathlib import Path

import pytest


def _load_live_cases():
    fixture = Path(__file__).resolve().parent / "cases.json"
    return json.loads(fixture.read_text(encoding="utf-8"))


@pytest.mark.live_llm
@pytest.mark.parametrize(
    "case",
    _load_live_cases(),
    ids=lambda item: item["id"],
)
def test_live_smoke_case(live_run, case):
    result = live_run(case)

    assert result["task_id"].startswith("live_")
    assert isinstance(result["answer"], str)
    assert result["answer"].strip()
    assert isinstance(result["tool_calls"], list)
    assert result["events"]
    assert result["report"]
