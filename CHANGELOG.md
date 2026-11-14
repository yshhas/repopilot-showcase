# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.12.0] - 2026-11-14

**Engineering hardening** release on top of **v0.11.0** — no runtime behavior changes.

#### Added

- `ruff.toml` with a project-wide static analysis policy (E501 ignored; `legacy/` uses per-file ignores).
- `tests/__init__.py` so `tests.*` imports resolve outside CI.
- `docs/archive/` index and archived historical release material.

#### Changed

- CI now runs the complete suite (`python -m pytest -q --tb=short`) instead of `--ignore=tests`.
- README restructured around use case, architecture, ReAct flow, tool safety, FSM, checkpoint, tests and limitations.
- Historical roadmaps, release audits and retrospectives moved to `docs/archive/`.
- Demo screenshots resized to 1280px; originals stay outside the repository.

#### Fixed

- 245 Ruff findings (E402/F401/F811/F841/F821/W292/E731), including unreachable dead code and shadowed duplicate tests.
- Inaccurate `.json` write/patch and Docker read-only mount descriptions.

#### Tests

**525** pytest passed, **4** `live_llm` deselected — verified locally and on GitHub Actions (Python 3.11 / 3.12). Ruff: 0 errors. Docker API smoke: 6/6.

## [0.11.0] - 2026-08-01

**Engineering Enhancement** release after **v0.10.2**. Adds LLM Provider abstraction, token-level context management, prompt externalization, CI/CD pipeline, Agent E2E testing, in-process observability, and LLM retry — without new ReAct tools and with full backward API compatibility.

#### Added

- **LLM Provider 抽象** — `llm/providers.py`；支持 DeepSeek / OpenAI / 本地 Ollama 热切换；`DEEPSEEK_API_KEY` 向后兼容 via `LLM_API_KEY` fallback
- **Token 级 Context 管理** — `_trim_memory()` 双模式（tiktoken `cl100k_base` 估算 + 字符回退）；保留 system message；`REACT_MAX_CONTEXT_TOKENS=0` 时行为与 v0.10.2 一致
- **Prompt 外置** — `config/prompts.json` + `config/prompts.py`；JSON 缺失时自动回退硬编码（`llm.py` 内联 fallback）
- **CI/CD** — `.github/workflows/ci.yml`；矩阵测试（Python 3.11 / 3.12）+ ruff lint + Docker 冒烟
- **Agent E2E 测试** — `test_agent_e2e.py`（5 cases）：只读 / 多工具 / 写入 / 观测性指标验证 / 纯文本回复路径
- **Observability** — `observability/` 模块；`record_llm_call()` / `record_tool_call()` / `record_agent_step_duration()` 埋点于 `react_agent.py` 主循环；`GET /metrics` JSON 端点 in `api/main.py`
- **LLM Retry** — `_create_with_retry()` in `llm.py`；429 / 5xx / 连接错误 3 次指数退避重试
- **Token Usage 统计** — `ContextVar` 从 API response 提取 `prompt_tokens` / `completion_tokens`，注入 observability metrics
- **Docker** — `Dockerfile` + `docker-compose.yml` 一键部署

#### Changed

- **`react_agent.py`** — observability 埋点在 LLM 调用后、工具调用后、每步结束三个时机
- **`llm.py`** — retry 包装 `_create_with_retry()` + prompt 外置 `load_prompts()` + token usage `get_last_token_usage()`
- **`config/settings.py`** — 新增 `LLM_PROVIDER` / `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` / `REACT_MAX_CONTEXT_TOKENS`
- **`.env.example`** — `DEEPSEEK_API_KEY` 注释化，推荐 `LLM_API_KEY`
- **`requirements.txt`** — 新增 `tiktoken>=0.8.0`
- **`APP_VERSION`** bumped to **`0.11.0`**

#### Compatibility

- ReAct tool count **15** unchanged（`verify_change` from v0.10.2）
- HTTP API signatures unchanged（新增 `GET /metrics` 端点）
- `DEEPSEEK_API_KEY` still supported as fallback（`LLM_API_KEY` 优先）
- Token mode disabled by default（`REACT_MAX_CONTEXT_TOKENS=0` → char mode）
- RAG / FSM / structured reject / dedup / checkpoint defaults unchanged

#### Tests

**525** complete pytest suite（**4** deselected live_llm）；verified locally and on GitHub Actions (Python 3.11 / 3.12).
Golden mock eval **26** cases。
Agent E2E **5** cases（`test_agent_e2e.py`）。
Token config **5** cases（`test_memory_trim_config.py`）。
Live LLM smoke **4** cases（opt-in `@pytest.mark.live_llm`）。

## [0.10.2] - 2026-07-23

**Verification loop** after **v0.10.1**. Adds minimal post-apply `verify_change` tool so the mutation path can close with an explicit check — without auto-fix, pytest-by-default, or workflow hard-gate to DONE.

#### Added

- **`verify_change` ReAct tool (#15)** — `tools/verify_change.py`; checks `patched_files` + Python `syntax` (MVP)
- **`VerificationSlice` on TMS** — last verify result persisted inside `mutation_state_json.verification` (workflow stays PATCHED)
- **Design** — [docs/design/verification_loop.md](docs/design/verification_loop.md)
- **Tests** — `test_verify_change.py` + golden pass/fail paths in `test_llm_golden.py`

#### Changed

- Prompt guides `apply_patch` / `write_repo_file` → `verify_change` → finish (soft)
- FSM soft-allows `verify_change` only from **PATCHED**; readonly mode blocks the tool
- **`APP_VERSION`** bumped to **`0.10.2`**

#### Compatibility

- HTTP API unchanged
- Verify fail **does not** rollback Git or FSM; agent may finish / rollback / re-patch
- Pre-0.10.2 checkpoints without `verification` hydrate as `NONE`

#### Tests

**515** default pytest cases (**4** deselected live_llm). Golden mock eval **26** cases (+2 verify).

## [0.10.1] - 2026-07-23

**Guard default-on migration** after **v0.10.0**. Turns on shipped mutation safety defaults without new ReAct tools, without HTTP API changes, and without enabling dedup.

#### Changed

- **`MUTATION_FSM_ENABLED` default `0` → `1`** — illegal mutation tool order is rejected by default (TMS-backed guard)
- **`STRUCTURED_TOOL_REJECT_ENABLED` default `0` → `1`** — gate rejects keep structured `{ok, code, message, details}`; ReAct memory still uses human-readable `message` text
- **`APP_VERSION`** bumped to **`0.10.1`**

#### Compatibility / rollback

- ReAct tools remain **14**; HTTP API unchanged
- **`EXECUTION_STATE_DEDUP_ENABLED` remains `0`** (deferred)
- Restore pre-0.10.1 behavior with env:
  - `MUTATION_FSM_ENABLED=0`
  - `STRUCTURED_TOOL_REJECT_ENABLED=0`
- Legacy modules retained for tests/hydrate; not removed

#### Tests

- **504** default pytest cases (**4** deselected live_llm)
- Added `test_default_on_guards.py` — default flag assertions, illegal-order reject, memory formatting, golden-style default FSM path
- Tool-unit suites that bypass workflow order explicitly opt out of FSM via fixtures

## [0.10.0] - 2026-07-21

**State Consolidation** release after **v0.9.0**. Unifies runtime mutation state under **TaskMutationState (TMS)**; checkpoint production save writes **`mutation_state_json` only**; v0.9 v1-column checkpoint hydrate preserved — **no new ReAct tools**, **no HTTP API changes**, **no default runtime flag changes**.

#### Docs (release polish · 2026-07-23)

- Aligned version / test-count claims across README, SECURITY, PROJECT_STATUS, architecture, workflow, demo docs (**497** default pytest)
- Removed broken README demo image embeds; `docs/assets/` PNG optional until recorded ([DEMO_RECORDING.md](docs/DEMO_RECORDING.md))
- Refresh [RELEASE_CHECKLIST.md](docs/archive/RELEASE_CHECKLIST.md) for v0.10.0 tag gate

#### Added

- **TaskMutationState (TMS) runtime (M1–M3 @ `8a0ee2f`…`e42bbb5`)** — `context/tms/` shadow ContextVar; `advance_from_outcome()` as sole business advance entry; checkpoint `mutation_state_json` v2 persist + hydrate
- **Task-scoped backup (M4 @ `23c7059`)** — `resolve_task_backup_ref()`; `TASK_SCOPED_BACKUP_ENABLED` flag (default `0`)
- **TMS guards + dedup readers (M5-a @ `9bdb33a`)** — `context/tms/guards.py`; `tool_manager` routes FSM guard and dedup skip through TMS when flags enabled
- **Resume TMS helpers (M5-d @ `4f08857`)** — `build_tms_resume_hint()`, `clear_tms_backup_milestones()`, `user_requests_rebackup()` in `context/tms/resume.py`
- **Release docs** — `docs/V0.10_RELEASE_SUMMARY.md`, `docs/V0.10_RELEASE_AUDIT.md`, `docs/GITHUB_RELEASE_v0.10.md`

#### Changed

- **`react_agent.py` (M5-b…M5-f)** — TMS-only tool advance; v2-only checkpoint save; resume hydrate → `set_shadow` only (no legacy mirror); no legacy module imports in production path
- **`storage/checkpoint_store.py` (M5-e @ `86c6046`)** — when `mutation_state` is present, v1 columns (`execution_state_json`, `mutation_fsm_json`) are forced NULL on insert
- **`tools/tool_manager.py` (M5-f @ `6592e2e`)** — FSM guard and dedup skip use TMS readers only; legacy ContextVar guard branches removed from runtime
- **`CHECKPOINT_MUTATION_STATE_V2_ENABLED`** — no longer gates react runtime save (M5-c); react always writes v2; flag retained for compat documentation
- **`APP_VERSION`** bumped to **`0.10.0`**

#### Compatibility

- ReAct tool count **14** unchanged
- HTTP API signatures unchanged
- Default feature flags unchanged (`MUTATION_FSM_ENABLED=0`, `EXECUTION_STATE_DEDUP_ENABLED=0`, `TMS_RUNTIME_SOT_ENABLED=0`, etc.)
- **v0.9 checkpoint resume** — v1-only rows hydrate via `hydrate_mutation_state_from_v1_columns`; mixed rows v2-wins
- Legacy modules (`mutation_fsm.py`, `execution_state.py`, `adapter.py`) **retained** for unit tests and hydrate compat; not used as production runtime SoT

#### Tests

**497** default pytest cases (**4** deselected live_llm). Golden mock eval **24** cases. Legacy import policy check passes.

## [0.9.0] - 2026-07-21

**Runtime Mutation Control** release after **v0.8.2**. Adds opt-in mutation workflow FSM, structured tool reject schema, FSM checkpoint hydrate, and golden illegal-order eval — **no new ReAct tools**, **no HTTP API changes**, **no default runtime flag changes**.

#### Added

- **Mutation FSM runtime (PR-F1 @ `5dd1e2a`)** — `context/mutation_fsm.py`; `MUTATION_FSM_ENABLED` flag (default `0`); `run_tool` ordering guard; states ANALYZING → … → DONE
- **FSM checkpoint hydrate (PR-F2 @ `47881d2`)** — `mutation_fsm_json` checkpoint column; resume restore; `mutation_fsm_blocked` audit; `mutation_fsm_restored` react_step
- **Structured tool reject (PR-S1 @ `77cb6c5`)** — `tools/result_schema.py`; `STRUCTURED_TOOL_REJECT_ENABLED` flag (default `0`); unified reject schema for FSM / mode / confirm / validation
- **FSM golden eval (PR-E1 @ `1d48e04`)** — +6 golden cases (18 → **24**): illegal-order blocks + legal diff-first chain + structured reject contract
- **Design / assessment docs** — `structured_tool_results.md` · `dedup_default_assessment.md` · FSM PR design notes

#### Changed

- **`APP_VERSION`** bumped to **`0.9.0`**
- Release documentation sync: `PROJECT_STATUS.md`, `architecture.md`, `workflow.md`, `README.md`, `SECURITY.md`, `testing_golden_eval.md`
- **`docs/design/mutation_fsm.md`** status → **Implemented** (opt-in flag)

#### Compatibility

- ReAct tool count **14** unchanged
- HTTP API signatures unchanged
- Default feature flags unchanged:
  - `MUTATION_FSM_ENABLED=0`
  - `STRUCTURED_TOOL_REJECT_ENABLED=0`
  - `EXECUTION_STATE_DEDUP_ENABLED=0`
  - `RAG_ENABLED=0`
- Flag off → v0.8.2 behavior preserved for existing golden / default CI

#### Tests

**424** default pytest cases (**4** deselected live_llm). Golden mock eval **24** cases. **4** opt-in live smoke cases (unchanged).

## [0.8.2] - 2026-07-20

Agent engineering proof release after **v0.8.1**. Extends golden eval, live smoke, and documentation — **no new ReAct tools**, **no HTTP API changes**, **no default runtime flag changes**. Mutation workflow FSM remains **design-only** (see `docs/design/mutation_fsm.md`); **not implemented** in this release.

#### Added

- **Golden eval resume dedup (PR-1)** — `test_golden_resume_dedup_skips_duplicate_apply` and `test_golden_resume_dedup_flag_off_does_not_skip_apply` in `test_llm_golden.py` (`1e9a2c4`)
- **Live mutation smoke (PR-2)** — opt-in case `full_mutation_sample_txt` with `confirm_callback`, disk assertions, and `tool_confirmation` audit checks (`56c41ee`)
- **`docs/RAG_DEMO.md` (PR-3)** — opt-in RAG build + hybrid search comparison guide (`c3b5515`)
- **`docs/design/mutation_fsm.md` (PR-4)** — **design-only** proposal for v0.9 runtime transition guards; `MUTATION_FSM_ENABLED` marked proposal/TBD (`3d88d65`)

#### Changed

- **`APP_VERSION`** bumped to **`0.8.2`**
- Release documentation sync: `PROJECT_STATUS.md`, `architecture.md`, `workflow.md`, `README.md`, testing runbooks

#### Compatibility

- ReAct tool count **14** unchanged
- HTTP API signatures unchanged
- Default feature flags unchanged (`EXECUTION_STATE_DEDUP_ENABLED=0`, `RAG_ENABLED=0`)
- **No runtime mutation FSM** — prompt-guided workflow + existing spot gates only

#### Tests

**369** default pytest cases (**363** v0.8.1 baseline + **6** from v0.8.2 eval work). **4** opt-in live smoke cases (`@pytest.mark.live_llm`). Golden mock eval **18** cases.

## [0.8.1] - 2026-07-20

Documentation-only patch after **v0.8.0**. Aligns core docs with the shipped v0.8 feature set and adds CI guards against documentation drift — no new ReAct tools, no HTTP API changes, no runtime behavior changes.

#### Changed

- **`docs/architecture.md`** — sync to v0.8.0: cancel/resume endpoints, checkpoint/dedup layers, config table, test inventory (**363** cases)
- **`docs/workflow.md`** — sync to v0.8.0: ReAct step boundaries, HTTP cancel/resume workflows
- **`docs/PROJECT_STATUS.md`** · **`docs/RELEASE_CHECKLIST.md`** — finalize v0.8.0 release state; document v0.8.1 scope
- **`docs/GITHUB_DEMO.md`** · **`examples/README.md`** — unify Demo B write target to `test.txt`
- **`test_project_docs.py`** — add architecture/workflow/github demo consistency tests (+3 cases)
- **`APP_VERSION`** bumped to **`0.8.1`**

#### Compatibility

- ReAct tool count **14** unchanged
- HTTP API signatures unchanged
- Default feature flags unchanged (`EXECUTION_STATE_DEDUP_ENABLED=0`, `RAG_ENABLED=0`)

## [0.8.0] - 2026-07-20

Eighth feature release after **v0.7.0**. **Agent Control + Live Eval**: checkpoint resume dedup for mutation milestones and an opt-in live LLM smoke eval framework — without new ReAct tools, without HTTP API changes, and with feature flags defaulting to v0.7 behavior.

#### Added

- **Execution state dedup (M1)** — `context/execution_state.py`; export/restore/update milestone state on checkpoint save and resume
- **`EXECUTION_STATE_DEDUP_ENABLED`** feature flag (default `0`) — when enabled, skip duplicate `git_create_backup`, `apply_patch`, and `write_repo_file` after resume
- **Resume hint injection** — checkpoint resume appends execution-state hint to ReAct memory when dedup is enabled
- **Live LLM smoke eval (PR-4)** — `tests/live_llm/` with `@pytest.mark.live_llm`, structural assertions, and 3 opt-in smoke cases
- **`docs/testing_live_llm_eval.md`** — live eval runbook and opt-in gates

#### Changed

- **`react_agent.py`** — checkpoint saves/restores real `execution_state`; resume injects dedup hint
- **`api/agent_runner.py`** — passes execution state through resume path
- **`tools/tool_manager.run_tool`** — dedup guard when `EXECUTION_STATE_DEDUP_ENABLED=1`
- **`pytest.ini`** — registers `live_llm` marker; default `addopts = -m "not live_llm"` so CI/default pytest never calls real LLM
- **`APP_VERSION`** bumped to **`0.8.0`**

#### Compatibility

- ReAct tool count **14** (no new tools)
- HTTP API signatures unchanged
- **`EXECUTION_STATE_DEDUP_ENABLED=0`** (default) → v0.7 checkpoint/resume behavior
- **`RAG_ENABLED=0`** (default) → unchanged v0.6/v0.7 search and propose paths
- Default pytest excludes live LLM smoke; manual opt-in requires `LIVE_LLM_EVAL_ENABLED=1` and valid `DEEPSEEK_API_KEY`

#### Known limitations (v0.8.0)

- **Dedup re-backup escape scope** — narrow keyword/path heuristics; not all user phrasing triggers re-backup
- **Dedup success detection** — relies on tool result markers for backup/apply milestones
- **Live smoke** — readonly + proposal-only cases; no live mutation chain (diff → backup → apply) yet
- **Mock RAG embedding default** — inherited from v0.7.0
- **No CLI cancel/resume flags** — HTTP API only

#### Tests

**360** default pytest cases in default CI run (**344** v0.7 baseline + M1 dedup + live smoke infrastructure + release docs). **3** additional opt-in live smoke cases (`@pytest.mark.live_llm`). Golden mock eval remains **16** cases.

## [0.7.0] - 2026-07-20

Seventh feature release after **v0.6.0**. **Repo RAG MVP**: adds semantic retrieval as an enhancement layer behind existing tools — hybrid search in `search_in_repo` and semantic context expand in `propose_code_changes` — without new ReAct tools and with **`RAG_ENABLED=0`** full v0.6 compatibility.

#### Added

- **RAG kernel (C1)** — `rag/` module: AST-aware chunker, mock embedding provider, Chroma vector store, `python -m rag.build`, `semantic_search()` API
- **Hybrid retrieval (C2)** — `HybridRetriever` with `GrepBackend` / `SymbolBackend` / `SemanticBackend`; `search_in_repo` optional hybrid merge (`RAG_HYBRID_ENABLED`)
- **Propose semantic expand (C3)** — task description → semantic file candidates merged into existing context budget ranking; context loaded via `read_repo_file` only
- **Audit** — `rag_query`, `rag_context_expand` events (metadata only; no embeddings or file bodies)
- **Retrieval eval fixture** — `tests/eval_retrieval/cases.json` baseline schema
- **Golden eval** — **14 → 16** cases (search orchestration + symbol lookup chain)

#### Changed

- **`index/ranking.py`** — `candidates_from_retrieval_hits()` for semantic ranking signal
- **`tools/repo_reader.py`** — grep kernel extracted; hybrid path when `RAG_ENABLED=1` and `RAG_HYBRID_ENABLED=1`
- **`tools/change_proposal.py`** — `_load_context_with_budget()` accepts `task_description` for semantic expand
- **`APP_VERSION`** bumped to **`0.7.0`**

#### Compatibility

- ReAct tool count **14** (no new tools)
- v0.6 index / context budget / cancel / checkpoint / batch patch unchanged
- **`RAG_ENABLED=0`** (default) → identical v0.6 behavior for search and propose paths
- **`RAG_CONTEXT_EXPAND=0`** or **`RAG_HYBRID_ENABLED=0`** opt-out per feature while RAG enabled

#### Known limitations (v0.7.0)

- **Mock embedding default** — `RAG_EMBEDDING_MODEL=mock-deterministic-v1`; semantic quality limited until real model switched
- **Full rebuild only** — no incremental embedding update after file edits
- **Python AST chunking primary** — JS/TS use sliding window only
- **No history task RAG** — audit/task memory not indexed for retrieval
- **Hybrid search output format** differs from legacy grep when RAG enabled (includes `[backend]` tags)

#### Deferred (post-v0.7.0)

- Production embedding model (Chroma default or sentence-transformers)
- Incremental embedding / file-watch rebuild
- History task / audit RAG retrieval
- JS/TS AST-aware chunking
- `read_repo_file` context budget integration

#### Tests

**316** pytest cases at RC (284 at v0.6.0 tag + RAG C1/C2/C3 + golden/eval coverage).

## [0.6.0] - 2026-07-20

Sixth feature release after **v0.5.0**. **Agent Control + Repo Understanding**: adds deterministic repo index, context budget for propose loading, cooperative task cancel, and checkpoint/resume over HTTP — while keeping ReAct **14** tools and v0.5 batch patch semantics.

#### Added

- **Repo Index Lite (C1)** — Python AST symbol/import index in `index/`; `database/repo_index.db`; `python -m index.build`; `INDEX_ENABLED=0` degrades to v0.5
- **FFD symbol mode (C2)** — `find_file_dependencies` extended with `symbol` / `query_mode` (`dependencies` | `symbol` | `auto`); legacy path-only behavior unchanged
- **Context budget + file ranking (C2)** — `propose_code_changes` load path uses ranking and truncation; audit `context_budget_applied` (metadata only); `CONTEXT_BUDGET_ENABLED=0` degrades to v0.5
- **Structured propose (P1)** — optional `affected_files` / `risk_notes` on `ChangeProposalList`; ranker prioritizes `affected_files` when present
- **Task cancel (C3)** — cooperative two-phase cancel (`request_cancel` → agent boundary → `mark_task_cancelled`); `POST /tasks/{id}/cancel`; status `cancelled`
- **Checkpoint / resume (C3)** — SQLite `task_checkpoints`; save after tool steps when `CHECKPOINT_ENABLED=1`; `POST /tasks/{id}/resume` restores memory, step, agent_mode, context budget state
- **Audit / report** — `cancel_requested`, `checkpoint_saved`, `task_cancelled`, `task_resumed` in task report summaries
- **Golden eval** — **11 → 14** cases (cancel before mutation, resume continues step, readonly cancel safe)

#### Changed

- **`react_agent.py`** — cancel boundary checks; checkpoint hooks; resume from checkpoint parameters
- **`api/main.py` · `api/agent_runner.py`** — cancel/resume HTTP endpoints and background resume scheduling
- **`storage/task_store.py`** — `cancel_requested` flag and `TASK_STATUS_CANCELLED`
- **`APP_VERSION`** bumped to **`0.6.0`**

#### Compatibility

- ReAct tool count **14** (no new tools)
- v0.5 single-file and batch `changes[]` patch flows unchanged
- `INDEX_ENABLED=0` / `CONTEXT_BUDGET_ENABLED=0` / `CHECKPOINT_ENABLED=0` preserve v0.5 behavior for opt-out deployments

#### Known limitations (v0.6.0)

- **No CLI `--cancel-task` / `--resume`** — HTTP API only for cancel/resume in this release
- **No `execution_state_json` dedup** — resume does not yet track backup/apply milestones to prevent duplicate mutation chains
- **Context budget** applies to `propose_code_changes` load path only; `read_repo_file` unchanged
- **Index** Python-only; symbol mode unavailable when `INDEX_ENABLED=0`
- **Golden eval is mock LLM orchestration** — does not replace live LLM evaluation

#### Not in scope (v0.6.0)

- RAG / embedding retrieval (deferred to v0.8)
- CLI cancel/resume flags
- Web UI
- v0.7 structured planning

#### Tests

**284** pytest cases (214 at v0.5.0 tag + index, context budget, checkpoint, cancel/resume API, and golden coverage).

## [0.5.0] - 2026-07-20

Fifth feature release after **v0.4.0**. **Engineering Trust + Multi-file Step-up**: extends existing **`generate_unified_diff`** and **`apply_patch`** (ReAct tools stay **14**) with unified **`changes[]`** batch patch, while **keeping** legacy single-file `path` + `new_content` and `write_repo_file` fallback.

#### Added

- **Multi-file batch patch** — `changes: [{path, new_content}, ...]` on `generate_unified_diff` / `apply_patch`; one combined diff, one `git apply --check`, one `git apply`
- **`normalize_to_changes`** — shared entry; legacy XOR `changes[]`
- **`build_batch_diff`** — shared preview/apply diff build + batch limits
- **`PATCH_MAX_FILES`** (default `10`); **`DIFF_ENGINE_VERSION=2`**
- **Batch audit** — `file_count`, `paths`, `failed_path` on `diff_preview` / `patch_apply` when `file_count > 1` (no raw diff / `new_content`)
- **Batch task report** — `Diff batch` / `Patch batch` summary lines
- **Alpha (Engineering Trust)** — doc sync (A1), LLM mock golden eval (A2), test isolation fixtures (A3), [multi_file_patch.md](docs/design/multi_file_patch.md) design (A4)
- **Golden eval** — **8 → 11** cases (batch orchestration + readonly boundaries)
- **Prompt / tool docs** — single-file first; batch `changes[]`; XOR args; forbids N× single-file apply for one logical multi-file task

#### Changed

- **`PATCH_MAX_CHANGED_LINES`** — enforced as **batch total** changed lines (single file = batch of 1)
- **`tool_confirm`** — batch `changes[]` display summary
- **`APP_VERSION`** bumped to **`0.5.0`**

#### Compatibility

- Legacy **`path` + `new_content`** unchanged for single-file callers
- **`changes=[one]`** equivalent to legacy single-file
- ReAct tool count **14** (no new tools)

#### Known limitations (v0.5.0)

- **No partial apply** — all-or-nothing batch by design
- **No auto-rollback** inside `apply_patch` (explicit `git_rollback` as in v0.4)
- **`git apply` is not a database transaction** — edge cases if apply aborts mid-flight (same class of risk as v0.4)
- **Golden eval is mock LLM orchestration** — does not replace live LLM evaluation
- No conflict merge / interactive hunk UI; no LLM-supplied raw diff apply

#### Not in scope (v0.5.0)

- New `apply_batch_patch` / `generate_batch_unified_diff` tools
- Multi-file `write_repo_file`
- Demo GIF multi-file update (v0.5.x candidate)
- task cancel / checkpoint (v0.5.x candidate)
- Web UI

#### Tests

**214** pytest cases (150 at v0.4.0 tag + alpha/beta batch patch, report, prompt, golden coverage).

## [0.4.0] - 2026-07-20

Fourth feature release after **v0.3.0**. Adds optional **diff-first** modify path while **keeping** `write_repo_file` whole-file overwrite. **Not** a multi-file patch engine.

#### Added

- **`generate_unified_diff`** — read-only single-file preview (`path` + `new_content`); available in `full` and `readonly`
- **`apply_patch`** — single-file apply via rebuilt unified diff + `git apply --check` + `git apply`; mutation tool with CLI/API confirm
- **`tools/diff_engine.py`** — diff build/validate/summarize; `preview_unified_diff` backend
- **`tools/patch_apply.py`** — `apply_repo_patch` / `apply_patch`; backup gate (`PATCH_REQUIRE_BACKUP`); no auto-rollback on failure
- **Audit events** — `diff_preview` (summary only, no raw diff in JSONL), `patch_apply` (success/failure + stats + backup metadata)
- **Task report** — aggregates `diff_preview` / `patch_apply` under 「写入 / Diff / Patch / Git / 确认」
- **Settings** — `PATCH_MAX_HUNKS`, `PATCH_MAX_CHANGED_LINES`, `PATCH_PREVIEW_MAX_LINES`, `PATCH_REQUIRE_BACKUP`, `DIFF_ENGINE_VERSION`
- **Prompt (S6)** — diff-first workflow recommended; `write_repo_file` documented as fallback; forbids LLM raw diff output

#### Changed

- ReAct tools: **12 → 14** (`generate_unified_diff`, `apply_patch`)
- `CONFIRM_REQUIRED_TOOLS`: adds `apply_patch` (with existing `write_repo_file`)
- `MUTATION_TOOLS` / readonly filter: blocks `apply_patch` in `readonly`
- `llm.py` system prompts — dual modify paths (recommended diff + legacy whole-file)
- `APP_VERSION` bumped to `0.4.0`

#### Not in scope (v0.4.0)

- Multi-file patches, merge/conflict resolution, interactive hunk editing
- Replacing or removing `write_repo_file`
- LLM-supplied raw unified diff apply
- Auto-rollback inside `apply_patch` (use `git_rollback` in agent flow)
- LangGraph / state-machine rewrite

#### Tests

**150** pytest cases (87 baseline at v0.3.0 tag + diff/patch/security/prompt/report coverage).

#### Post-v0.3.0 housekeeping (already on `master` before v0.4 branch)

- `SECURITY.md`, legacy consolidation under `legacy/`, RepoPilot rebrand, demo assets — see commits before `feature/unified-diff-mvp`

## [0.3.0] - 2026-07-19

Fourth release — **showcase & service hardening** (v0.3.0 P1/P2). No Agent core expansion.

### Added

#### P1 — Read-path redaction

- `security/redaction.py` — env/assignment/Bearer/sk- pattern redaction
- Audit JSONL redact via `audit/audit_log.py` (before length truncation)
- `read_repo_file` / `search_in_repo` output redaction
- Path blocking for `.env`, credentials, key files (existing; tests extended)

#### P2 — API Key authentication

- `api/auth.py` HTTP middleware: optional `API_KEY` env + `X-API-Key` header
- `/health` exempt; empty/whitespace `API_KEY` disables auth (v0.2.2 compatible)
- `scripts/api_smoke_test.py --api-key` for secured deployments

#### P0 — Demo assets (GIF + screenshots)

- `docs/DEMO_RECORDING.md`, `docs/assets/`, README demo preview section
- `demo-cli-read.gif`, `demo-cli-modify.gif`, `demo-cli-report.gif`, `demo-audit-report.jpg`, `demo-api-health.png`

### Changed

- `APP_VERSION` bumped to `0.3.0`
- `docs/workflow.md`, `docs/architecture.md`, `docs/PROJECT_STATUS.md` updated

### Tests

87 pytest cases (66 at v0.2.2 + 21 new: P1 ×11, P2 ×10).

### Commit History (v0.3.0)

```
b26b7b9 chore: prepare v0.3.0 release
6b22e97 feat: P2 optional API Key auth for HTTP endpoints (v0.3.0)
4d79828 feat: P1 read-path redaction for audit and repo_reader (v0.3.0)
5f2f130 docs: v0.3.0 milestone summary (P1/P2 done, P0 assets pending)
```



## [0.2.2] - 2026-07-19

Patch release — **Docker reproducibility & CI docker verification** (C8 completion).

### Added

- GitHub Actions CI workflow (pytest on push/PR)
- Docker Compose one-command API startup (`docker compose up`)
- CI **docker** job: `docker compose build` → `up` → health wait → `api_smoke_test.py`
- `scripts/api_smoke_test.py --health-only` for Docker/CI without LLM
- Dockerfile: `git init` + baseline commit so `git_*` tools work inside container

### Fixed

- Lazy OpenAI client initialization so pytest collects without `DEEPSEEK_API_KEY` in CI

### Changed

- `APP_VERSION` bumped to `0.2.2`
- `docs/workflow.md` — HTTP API workflow, AGENT_MODE, updated limitations (C7 sync)
- `docs/demo.md` — Demo E (API readonly), Demo F (Docker), 66-test pytest note

### Tests

66 pytest cases; CI runs pytest (Python 3.12) + docker smoke on ubuntu-latest.

### Commit History (v0.2.2)

```
b6448f9 chore: prepare v0.2.2 release (C8 Docker CI)
e4a8806 feat: Docker CI verification and C8 doc sync (v0.2.2 prep)
739d6cb docs: C8 acceptance summary in PROJECT_STATUS
cdc8a48 feat: add Docker Compose for one-command API startup
6a9114c fix: lazy OpenAI client init for CI pytest collection
50ad334 ci: add GitHub Actions pytest workflow and README badge
```

## [0.2.1] - 2026-07-19

Third release — **AGENT_MODE runtime switching** (C7).

Baseline commit: `5886ef0` (C7 AGENT_MODE).

### Added

#### AGENT_MODE (C7)

- Runtime agent modes: `full` (default) and `readonly`
- **readonly**: allows read/analyze tools + `propose_code_changes` + `git_status`; blocks `git_create_backup`, `write_repo_file`, `git_rollback`
- Environment variable `AGENT_MODE`; API per-task override via `POST /tasks` body `mode` field
- Priority: `request.mode` > `AGENT_MODE` env > default `full`
- SQLite `tasks.agent_mode` column persisted for audit/report
- `GET /health` returns default `agent_mode`
- Module `config/agent_mode.py`; ContextVar in `audit/context.py`

### Changed

- `APP_VERSION` bumped to `0.2.1`
- Dynamic system prompt via `build_system_prompt(mode)` in `llm.py`
- Task audit report includes agent mode

### Tests

13 additional pytest cases (66 total with `python -m pytest -v`).

### Commit History (v0.2.1)

```
fc464b5 chore: prepare v0.2.1 release (C7 AGENT_MODE)
5886ef0 feat: C7 AGENT_MODE readonly/full with API per-task override
```

## [0.2.0] - 2026-07-19

Second release — **CLI + FastAPI HTTP API** (C3–C6).

Baseline commit: `beb7912` (HTTP API layer), version bump and documentation in this release prep commit.

### Added

#### HTTP API (C3–C6)

- FastAPI application (`api/main.py`) with health check and task endpoints
- **C3** — read-only task API:
  - `GET /health` — service status and version
  - `GET /tasks` — list recent tasks (limit query param)
  - `GET /tasks/{task_id}` — single task detail
- **C4** — async task submission:
  - `POST /tasks` — create task, run ReAct agent in background thread (`api/agent_runner.py`)
- **C5** — Server-Sent Events streaming:
  - `GET /tasks/{task_id}/stream` — live audit events (`api/task_stream.py`)
  - SSE hooks in `audit/context.py` and `audit/audit_log.py`
- **C6** — report and API write confirmation:
  - `GET /tasks/{task_id}/report` — Markdown audit report (reuses `audit/task_report.py`)
  - `GET /tasks/{task_id}/confirm/pending` — pending write confirmation status
  - `POST /tasks/{task_id}/confirm` — approve/reject pending tool execution (`api/task_confirm.py`)
  - SSE `confirmation_required` events; configurable `API_CONFIRM_TIMEOUT_SECONDS` (default 300s)
- Live smoke test script: `scripts/api_smoke_test.py`
- Integrated acceptance tests: `test_api_acceptance.py`

#### Configuration

- `APP_VERSION`, `API_DEFAULT_LIST_LIMIT`, `API_MAX_LIST_LIMIT`, `API_CONFIRM_TIMEOUT_SECONDS` in `config/settings.py`

### Changed

- `APP_VERSION` bumped to `0.2.0`
- `react_agent.py` — skip duplicate `create_task` when task already exists (API-created tasks)
- `requirements.txt` — add `fastapi`, `uvicorn`
- README, `docs/architecture.md`, `docs/PROJECT_STATUS.md` — document HTTP API layer

### Tests

20 additional pytest cases (53 total with `python -m pytest -v`):

| Module | Coverage |
|--------|----------|
| `test_api_c3.py` | Health, list/get tasks |
| `test_api_c4.py` | POST /tasks, validation |
| `test_api_c5.py` | SSE stream replay and live events |
| `test_api_c6.py` | Report, confirm/pending, confirm flow |
| `test_api_acceptance.py` | C3–C6 integrated TestClient flow |

`conftest.py` excludes interactive scripts `test_ai.py` and `test_react.py` from collection.

### Commit History (v0.2.0)

```
beb7912 feat: add FastAPI HTTP API layer (C3-C6)
```

## [0.1.0] - 2026-07-19

First public release — **CLI Enterprise Dev Agent MVP**.

Baseline commit: `ef1f4db` (documentation), release preparation includes LICENSE and this changelog.

### Added

#### Core Agent

- ReAct CLI agent (`react_agent.py`) with multi-turn session memory
- DeepSeek LLM integration and structured system prompts (`llm.py`)
- Pydantic tool argument models and agent response parsing (`schemas.py`)
- 12 ReAct tools registered via `tools/tool_manager.py`:
  - Read/analyze: `list_repo_files`, `read_repo_file`, `search_in_repo`, `analyze_repo_structure`, `find_file_dependencies`
  - Change workflow: `propose_code_changes`, `git_status`, `git_create_backup`, `write_repo_file`, `git_rollback`
  - Utility: `summarizer`, `calculator`
- Standard change workflow: propose → user confirm → Git backup → controlled write → rollback

#### Security

- Path guard (`security/path_guard.py`): repo boundary checks, sensitive file blocking, extension whitelist, ignored directories
- Controlled write (`tools/safe_write.py`): writable extension whitelist (excludes `.json`), 100KB size limit, UTF-8 only, no auto-create directories
- CLI y/n confirmation for `write_repo_file` (`security/tool_confirm.py`)
- Git safety net: backup branch (`agent-backup/<timestamp>`) and `git reset --hard` rollback
- Cross-process backup state in `logs/last_backup.json`

#### Observability

- Append-only JSONL audit log (`logs/audit.jsonl`) for tool calls, ReAct steps, writes, Git ops, proposals, confirmations
- SQLite task persistence (`database/tasks.db`) with status, question, answer, timestamps
- Per-task audit summary report (`audit/task_report.py`, CLI: `python -m audit.task_report <task_id>`)
- Structured application logging (`logs/app.log`)

#### Configuration

- Centralized settings (`config/settings.py`): `REPO_ROOT`, `REACT_MAX_STEPS`, `MAX_WRITE_BYTES`, security lists
- Environment-based configuration via `.env` (`DEEPSEEK_API_KEY`, etc.)

#### Documentation

- GitHub-oriented README with architecture diagrams, demo examples, and doc index
- `docs/architecture.md` — system design and data flow
- `docs/workflow.md` — read-only and change workflows, dual confirmation
- `docs/demo.md` — reproducible demo scripts and checklist
- `docs/PROJECT_STATUS.md` — maintainer status and milestones

#### License

- MIT License (`LICENSE`)

### Changed

- Unified read security: ReAct uses `read_repo_file` only; `file_reader` excluded from ReAct tools (B4)
- ReAct max steps default set to 20 (B5)
- System prompts aligned with full change workflow rules (B6)

### Tests

33 automated pytest cases, all passing:

| Module | Coverage |
|--------|----------|
| `test_parse_agent_response.py` | JSON / markdown / mixed text parsing |
| `test_change_proposal.py` | Change proposal schema |
| `test_backup_persistence.py` | Backup JSON persistence and cross-process rollback |
| `test_file_reader_security.py` | Read security and file_reader isolation |
| `test_react_max_steps.py` | Step limit and finish behavior |
| `test_llm_prompt.py` | Prompt workflow rules |
| `test_task_store.py` | SQLite task CRUD and react_agent persistence |
| `test_task_report.py` | Audit report generation |
| `test_project_docs.py` | README and requirements sanity checks |

```powershell
python -m pytest test_parse_agent_response.py test_change_proposal.py test_backup_persistence.py test_file_reader_security.py test_react_max_steps.py test_llm_prompt.py test_task_store.py test_task_report.py test_project_docs.py -v
```

### Known Limitations

- **CLI only** — no HTTP API, SSE, or web UI
- **Full-file overwrite** — no unified diff or patch apply
- **Single backup record** — only the latest entry in `last_backup.json`
- **No AGENT_MODE** — cannot switch read-only vs full capability at runtime
- **Session-scoped task_id** — one task ID per CLI session across multiple turns
- **Content redaction incomplete** — `SENSITIVE_*` constants defined but not applied on read path; audit log truncates fields only
- **Write without backup allowed** — warns but does not block when no backup exists
- **Destructive rollback** — `git reset --hard` discards unbackuped changes
- **Legacy code coexistence** — `agent.py` (RAG) and `main.py` (demo) are separate from the ReAct main flow

### Commit History (v0.1.0)

```
ba6dc5d initial commit
3d29dde chore: expand gitignore and stop tracking runtime files
a736fe6 feat: B1-B3 safe write, confirmation, backup persistence
35bb515 feat: B4 unify read security via read_repo_file
e2b7991 feat: B5 add ReAct max steps limit
8ecedd2 feat: B6 align ReAct prompts with full change workflow
ecb5f5d docs: B7 add requirements.txt and README
100fac4 feat: C1 persist agent tasks to SQLite
ab4a446 feat: C2 task audit report and MVP documentation
ef1f4db docs: v0.1-mvp GitHub presentation docs and README
```


