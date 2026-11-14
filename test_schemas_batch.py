import pytest
from pydantic import ValidationError

from schemas import (
    ApplyPatchArgs,
    FileChange,
    GenerateUnifiedDiffArgs,
    normalize_to_changes,
)


def test_normalize_to_changes_legacy_path_and_content():
    changes, error = normalize_to_changes(
        path="foo.py",
        new_content="print(1)\n",
    )

    assert error is None
    assert len(changes) == 1
    assert changes[0].path == "foo.py"
    assert changes[0].new_content == "print(1)\n"


def test_normalize_to_changes_from_changes_list():
    changes, error = normalize_to_changes(
        changes=[
            {"path": "a.py", "new_content": "a\n"},
            {"path": "b.py", "new_content": "b\n"},
        ],
    )

    assert error is None
    assert len(changes) == 2
    assert [item.path for item in changes] == ["a.py", "b.py"]


def test_normalize_to_changes_normalizes_backslashes():
    changes, error = normalize_to_changes(
        changes=[{"path": "dir\\file.py", "new_content": "x\n"}],
    )

    assert error is None
    assert changes[0].path == "dir/file.py"


def test_normalize_to_changes_rejects_mixed_modes():
    changes, error = normalize_to_changes(
        path="a.py",
        new_content="a\n",
        changes=[{"path": "b.py", "new_content": "b\n"}],
    )

    assert changes is None
    assert "不能同时使用" in error


def test_normalize_to_changes_rejects_empty_input():
    changes, error = normalize_to_changes()

    assert changes is None
    assert "需要提供" in error


def test_normalize_to_changes_rejects_empty_changes_list():
    changes, error = normalize_to_changes(changes=[])

    assert changes is None
    assert "需要提供" in error


def test_normalize_to_changes_rejects_duplicate_paths():
    changes, error = normalize_to_changes(
        changes=[
            {"path": "same.py", "new_content": "a\n"},
            {"path": "same.py", "new_content": "b\n"},
        ],
    )

    assert changes is None
    assert "重复路径" in error


def test_normalize_to_changes_rejects_too_many_files(monkeypatch):
    import config.settings as settings

    monkeypatch.setattr(settings, "PATCH_MAX_FILES", 2)

    changes, error = normalize_to_changes(
        changes=[
            {"path": "a.py", "new_content": "a\n"},
            {"path": "b.py", "new_content": "b\n"},
            {"path": "c.py", "new_content": "c\n"},
        ],
    )

    assert changes is None
    assert "超过上限" in error


def test_generate_unified_diff_args_accepts_legacy():
    args = GenerateUnifiedDiffArgs.model_validate(
        {"path": "sample.txt", "new_content": "updated\n"},
    )

    assert args.path == "sample.txt"
    assert args.new_content == "updated\n"
    assert args.changes is None


def test_generate_unified_diff_args_accepts_changes():
    args = GenerateUnifiedDiffArgs.model_validate(
        {
            "changes": [
                {"path": "a.py", "new_content": "a\n"},
                {"path": "b.py", "new_content": "b\n"},
            ],
        },
    )

    assert len(args.changes) == 2
    assert args.path is None


def test_generate_unified_diff_args_rejects_mixed_modes():
    with pytest.raises(ValidationError):
        GenerateUnifiedDiffArgs.model_validate(
            {
                "path": "a.py",
                "new_content": "a\n",
                "changes": [{"path": "b.py", "new_content": "b\n"}],
            },
        )


def test_apply_patch_args_shares_same_shape():
    args = ApplyPatchArgs.model_validate(
        {"path": "sample.txt", "new_content": "updated\n"},
    )

    assert args.path == "sample.txt"
    assert args.changes is None


def test_file_change_requires_path_and_content():
    with pytest.raises(ValidationError):
        FileChange.model_validate({"path": "a.py"})
