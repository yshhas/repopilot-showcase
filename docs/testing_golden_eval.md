# Golden Eval（LLM Mock）

> **版本**：v0.5.0 RC · PR-B4 + PR-RC  
> **测试文件**：`test_llm_golden.py` · **Fixtures**：`conftest.py`

## 目的

Golden eval 验证 **`react_agent()` 编排契约**：在预设 LLM 输出下，工具调用顺序、模式边界、循环终止是否正确。

**不负责**：prompt 文案（`test_llm_prompt.py`）、diff/apply 算法、confirm UI、真实 DeepSeek 调用。

## Mock 边界

| 组件 | 做法 |
|------|------|
| `ask_ai` | `mock_ask_ai_sequence["install"]([...])` → patch `react_agent.ask_ai` |
| `run_tool` | **Mode A**：`tool_call_spy["install"]()` stub + 记录 calls · **Mode B**：`use_real_run_tool=True` |
| `parse_agent_response` | 真实 |
| Task DB | 需要时显式使用 `isolated_task_db` |

无 `DEEPSEEK_API_KEY` 时必须全绿。

## 如何新增 case

1. 在 `test_llm_golden.py` 增加 `test_golden_*` 函数。
2. 注入 fixture：`mock_ask_ai_sequence`、`tool_call_spy`；需要 task 断言时加 `isolated_task_db`。
3. 配置 LLM 响应序列（ToolCall JSON 或纯文本）。
4. Mode A：spy 后断言 `[c["action"] for c in tool_call_spy["calls"]]`、`ask_ai` 次数、forbidden tools。
5. Mode B（仅 agent_mode / `run_tool` 边界）：`tool_call_spy["install"](use_real_run_tool=True)`，断言 memory 中工具结果含 `readonly` 等。
6. 运行：`python -m pytest test_llm_golden.py -v`

**Mode 比例建议**：编排契约用 Mode A；`is_tool_allowed` 等真实拦截用 Mode B（少量）。

`changes[]` 等多文件契约在 B4 通过 golden case G9–G11 覆盖（batch 编排、readonly 边界）。

## 当前 case（24）

| Case | 模式 | 要点 |
|------|------|------|
| `readonly_analysis_no_mutation` | A | 只读 tool，无 mutation |
| `full_proposal_without_mutation` | A | 仅 `propose_code_changes` |
| `full_diff_first_chain` | A | 单文件 diff → backup → apply 顺序 |
| `full_batch_diff_first_chain` | A | batch `changes[]` preview → backup → apply（2 文件） |
| `full_finish_terminates_loop` | A | tool → finish |
| `readonly_allows_diff_preview` | A | readonly 允许单文件 preview |
| `readonly_allows_batch_diff_preview` | A | readonly 允许 batch preview |
| `plain_text_answer_no_tool` | A | 无 tool 直接回答 |
| `readonly_blocks_apply_patch_real_run_tool` | B | agent_mode 拦截单文件 apply |
| `readonly_blocks_git_create_backup_real_run_tool` | B | agent_mode 拦截 backup |
| `readonly_blocks_batch_apply_patch_real_run_tool` | B | agent_mode 拦截 batch apply |
| `cancel_before_mutation` | A | cancel 在 mutation 前 |
| `resume_continues_step` | A | checkpoint resume 继续 |
| `resume_dedup_skips_duplicate_apply` | B | resume dedup skip apply（v0.8.2） |
| `resume_dedup_flag_off_does_not_skip_apply` | B | dedup flag off 不 skip（v0.8.2） |
| `readonly_cancel_safe` | A | readonly cancel |
| `readonly_search_in_repo_orchestration` | A | search 编排 |
| `readonly_search_then_symbol_lookup` | A | search → symbol |
| `fsm_apply_before_backup` | B | FSM block：未 backup 直接 apply（`MUTATION_FSM_ENABLED=1`） |
| `fsm_backup_before_propose` | B | FSM block：未 propose 就 backup |
| `fsm_diff_before_propose` | B | FSM block：未 propose 就 preview diff |
| `fsm_write_repo_blocked_on_diff_first_path` | B | diff-first 路径误用 `write_repo_file` |
| `fsm_legal_diff_chain` | B | propose → diff → backup → apply 合法全链 |
| `fsm_structured_reject_contract` | B | STR+FSM on：memory/audit structured reject 契约 |
