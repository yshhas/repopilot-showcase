import json
from pathlib import Path


def test_eval_retrieval_cases_fixture_schema():
    fixture = Path(__file__).resolve().parent / "cases.json"
    cases = json.loads(fixture.read_text(encoding="utf-8"))

    assert isinstance(cases, list)
    assert len(cases) >= 5

    for item in cases:
        assert "id" in item
        assert "query" in item
        assert "expected_paths" in item
        assert isinstance(item["expected_paths"], list)
        assert item.get("top_k", 5) >= 1
        assert item.get("min_hits", 1) >= 1
