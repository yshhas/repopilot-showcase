from index.ranking import (
    FileCandidate,
    apply_context_budget,
    candidates_from_paths,
    rank_file_candidates,
)


def test_rank_file_candidates_orders_by_score():
    ranked = rank_file_candidates([
        FileCandidate(path="b.py", score=10.0, sources=["target_files"]),
        FileCandidate(path="a.py", score=100.0, sources=["affected_files"]),
    ])

    assert [item.path for item in ranked] == ["a.py", "b.py"]


def test_apply_context_budget_truncates_by_rank_and_budget():
    candidates = candidates_from_paths(
        ["f1.py", "f2.py", "f3.py", "f4.py"],
        source="target_files",
        score=50.0,
    )
    ranked = rank_file_candidates(candidates)

    result = apply_context_budget(
        ranked,
        budget_chars=5000,
        rank_source="target_files",
        file_char_estimates={
            "f1.py": 2000,
            "f2.py": 2000,
            "f3.py": 2000,
            "f4.py": 2000,
        },
    )

    assert result.candidates_count == 4
    assert result.selected_count < 4
    assert result.truncated_count > 0
    assert result.truncation_reason in {"budget_exceeded", "rank_cut"}
