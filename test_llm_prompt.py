from llm import (
    REACT_BASE_PROMPT,
    REACT_CHANGE_PROMPT,
    REACT_READONLY_PROMPT,
    REACT_RULES_PROMPT,
    build_system_prompt,
    system_prompt,
)


def test_system_prompt_includes_full_change_workflow():

    combined = REACT_BASE_PROMPT + REACT_CHANGE_PROMPT + REACT_RULES_PROMPT

    assert "propose_code_changes" in combined

    assert "git_create_backup" in combined

    assert "write_repo_file" in combined

    assert "generate_unified_diff" in combined

    assert "apply_patch" in combined

    assert "git_rollback" in combined

    assert "read_repo_file" in combined

    assert "file_reader" in combined

    assert "last_backup.json" in combined


def test_system_prompt_recommends_unified_diff_workflow():

    assert "推荐路径（unified diff" in REACT_CHANGE_PROMPT

    assert "generate_unified_diff" in REACT_CHANGE_PROMPT

    assert "apply_patch" in REACT_CHANGE_PROMPT

    assert "git_create_backup（apply_patch 前必须先备份）" in REACT_CHANGE_PROMPT


def test_system_prompt_keeps_write_repo_file_fallback():

    assert "备选路径（整文件覆盖" in REACT_CHANGE_PROMPT

    assert "write_repo_file" in REACT_CHANGE_PROMPT


def test_system_prompt_forbids_raw_unified_diff_output():

    assert "raw unified diff" in REACT_CHANGE_PROMPT

    assert "raw unified diff" in REACT_RULES_PROMPT

    assert "不要自行输出 raw unified diff" in REACT_BASE_PROMPT


def test_system_prompt_forbids_finish_as_confirmation():

    assert "禁止用 finish 代替用户确认" in REACT_CHANGE_PROMPT

    assert "不要用 finish 来询问用户是否执行" in REACT_RULES_PROMPT


def test_system_prompt_no_longer_blocks_all_writes():

    assert "只能生成修改方案" not in REACT_BASE_PROMPT

    assert "write_repo_file" in REACT_BASE_PROMPT


def test_system_prompt_built_with_tools_section():

    assert "write_repo_file" in system_prompt

    assert "generate_unified_diff" in system_prompt

    assert "apply_patch" in system_prompt

    assert "git_rollback" in system_prompt

    assert "git_create_backup" in system_prompt


def test_full_system_prompt_includes_diff_example():

    prompt = build_system_prompt("full")

    assert '"action": "generate_unified_diff"' in prompt

    assert '"action": "apply_patch"' in prompt

    assert '"action": "write_repo_file"' in prompt


def test_readonly_system_prompt_allows_propose_only():

    readonly_prompt = build_system_prompt("readonly")

    assert "propose_code_changes" in readonly_prompt

    assert "generate_unified_diff" in readonly_prompt

    assert "apply_patch" in REACT_READONLY_PROMPT

    assert "禁止" in REACT_READONLY_PROMPT

    assert REACT_READONLY_PROMPT.strip() in readonly_prompt

    assert REACT_CHANGE_PROMPT.strip() not in readonly_prompt


def test_readonly_system_prompt_blocks_apply_patch_not_preview():

    readonly_prompt = build_system_prompt("readonly")

    assert "generate_unified_diff 预览" in readonly_prompt or (
        "generate_unified_diff" in readonly_prompt
        and "只读" in readonly_prompt
    )

    assert "apply_patch" in REACT_READONLY_PROMPT

    assert REACT_CHANGE_PROMPT.strip() not in readonly_prompt


def test_change_prompt_documents_batch_changes():

    assert "changes" in REACT_CHANGE_PROMPT

    assert "多文件" in REACT_CHANGE_PROMPT

    assert "path/new_content 与 changes 二选一" in REACT_CHANGE_PROMPT


def test_change_prompt_single_file_still_primary():

    single_index = REACT_CHANGE_PROMPT.index("单文件修改（默认，优先使用")

    batch_index = REACT_CHANGE_PROMPT.index("多文件修改（仅当方案明确涉及")

    assert single_index < batch_index

    assert "不要用 batch" in REACT_CHANGE_PROMPT

    assert "generate_unified_diff(path, new_content)" in REACT_CHANGE_PROMPT


def test_change_prompt_forbids_loop_single_apply_for_batch():

    assert "禁止多文件任务用多次单文件 apply_patch" in REACT_CHANGE_PROMPT

    assert "禁止单文件修改滥用 changes[] batch" in REACT_CHANGE_PROMPT


def test_rules_prompt_keeps_single_file_example_before_batch():

    single_example = REACT_RULES_PROMPT.index(
        '"action": "generate_unified_diff", "args": {"path": "test.txt"'
    )

    batch_example = REACT_RULES_PROMPT.index('"changes": [{"path": "a.py"')

    assert single_example < batch_example


def test_tools_prompt_includes_changes_parameter():

    prompt = build_system_prompt("full")

    assert '"changes"' in prompt

    assert "二选一" in prompt
