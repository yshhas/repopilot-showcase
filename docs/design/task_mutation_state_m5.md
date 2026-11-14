# PR-M5 — Legacy State Path Removal Design

> **Status**: **Design · v0.10 PR-M5** · (2026-07-21)  
> **Baseline**: PR-M4 (pending commit) · 480 pytest passed  
> **Parent**: [task_mutation_state.md](task_mutation_state.md) · [task_mutation_state_m4.md](task_mutation_state_m4.md) · [V0.10_ROADMAP.md](../archive/V0.10_ROADMAP.md)  
> **Out of scope (M5)**: 运行时代码 · commit · worktree 隔离 (P2) · verify loop (V0/V1) · FSM/dedup default-on (D2/P2) · SQLite 列物理删除 · RAG 改动

---

## English Summary

**PR-M5** removes the parallel legacy mutation paths (`mutation_fsm.py`, `execution_state.py` marker advance, TMS↔legacy dual-write) so **TMS shadow is the sole runtime SoT** for FSM guards, dedup skip, backup resolution, and checkpoint export. Checkpoint **save** writes **`mutation_state_json` only** (v1 columns stop being updated); **read** still hydrates v0.9 rows from v1 columns. `advance_from_outcome()` remains the only business advance entry. Compat shims and feature flags from M1–M4 (`TMS_ADAPTER_ENABLED`, parity strict, legacy mirror) are removed or collapsed.

---

## 1. PR-M5 目标与 scope guard

### 1.1 问题陈述（M4 后仍存在的结构性债）

| 现象 | 根因 |
|------|------|
| 三轨状态仍并存 | TMS shadow + `execution_state` ContextVar + `mutation_fsm` ContextVar |
| Guard/dedup 读 legacy | `tool_manager._mutation_fsm_check` / `_execution_state_dedup_skip` 未读 TMS |
| Checkpoint save 双写 | `execution_state_json` + `mutation_fsm_json` + `mutation_state_json` |
| Resume 后 legacy mirror | `mirror_tms_to_legacy()` 把 TMS 刷回 global/execution_state |
| Marker 路径仍存在于代码库 | `update_from_tool_result` / `advance_mutation_fsm_on_success` 可被测试直接调用 |
| M1 过渡 flag 未清理 | `TMS_ADAPTER_ENABLED`, `PARITY_STRICT`, adapter sync 路径 |

### 1.2 目标

| # | 交付 |
|---|------|
| G1 | **Runtime SoT = TMS shadow** — guards、dedup、backup gate 统一读 TMS |
| G2 | **删除** legacy marker advance 与 FSM 独立 advance 路径（保留 v1 hydrate 只读） |
| G3 | Checkpoint **save** 仅 export `mutation_state_json`（默认 v2 on） |
| G4 | Resume：`hydrate_checkpoint_mutation_state()` → `set_shadow` **only**（无 legacy mirror） |
| G5 | 移除 `sync_tms_from_legacy` / `mirror_tms_to_legacy` / `build_tms_from_legacy` 运行时调用 |
| G6 | 迁移 shim：可选 1-minor `mutation_fsm.py` re-export → 下版本删 |
| G7 | Golden + migration tests 全绿；v0.9 checkpoint hydrate 仍工作 |

### 1.3 M5 不做

| 项 | 归属 |
|----|------|
| Git worktree / sandbox 隔离 | v0.11 P2 |
| `verify_change` / VerificationSlice | V0/V1 |
| `MUTATION_FSM_ENABLED` default → 1 | D2 · v0.10.1 |
| `EXECUTION_STATE_DEDUP_ENABLED` default → 1 | P2 · v0.11 |
| 物理删除 SQLite v1 列 | v0.10.1+ schema migration |
| 删除 `logs/last_backup.json` 与 `project_context` backup API | v0.10.1 deprecate doc；narrow fallback 可部分在 M5 |
| Checkpoint `schema_version` breaking bump | v0.11+ |
| String marker compat parse 完全删除 | M5 可 deprecate audit；硬删交 v0.10.1 |

### 1.4 M5 完成后的系统性质

| 属性 | M5 后 |
|------|-------|
| 状态变化入口 | **仅** `ToolOutcome → advance_from_outcome()` |
| Runtime guard SoT | **TMS shadow** |
| Checkpoint mutation authority | **`mutation_state_json` only (write)** |
| v0.9 checkpoint read | v1 列 → TMS hydrate（只读 compat） |
| Legacy modules | 删除或 thin re-export shim |
| Global backup file | 读 fallback 保留（CLI）；create 不写 global（scoped=1 已在 M4） |

### 1.5 核心原则（M2–M4 延续）

```
ToolOutcome
    ↓
advance_from_outcome()        ← 唯一推进入口（不变）
    ↓
TMS shadow                    ← 唯一 runtime SoT（M5）
    ↓
checkpoint save → mutation_state_json only
```

**禁止（M5 后）**：

```
post-tool → update_from_tool_result(marker)     ❌
post-tool → advance_mutation_fsm_on_success     ❌
hydrate → mirror_tms_to_legacy                  ❌
save → execution_state_json / mutation_fsm_json ❌
```

---

## 2. 现状 vs 目标

### 2.1 M4 今天

| 层 | 行为 |
|----|------|
| Advance | `advance_from_outcome()` + `_mirror_milestone_to_legacy` |
| Guards | `mutation_fsm.check_*` + `execution_state.should_skip_tool` |
| Backup read | `resolve_task_backup_ref()`（TMS / legacy / global fallback） |
| Checkpoint save | v1 + v2 dual-write（v2 flag） |
| Resume | hydrate v2 → v1 merge → `mirror_tms_to_legacy` |
| Cancel / resume mid-run | `_sync_tms_from_legacy_safe` |

### 2.2 M5 目标

| 层 | 行为 |
|----|------|
| Advance | `advance_from_outcome()` → TMS only |
| Guards | TMS readers: `check_mutation_allowed`, `should_skip_tool_tms` |
| Backup read | `resolve_task_backup_ref()` — TMS-first；legacy_execution fallback **移除** |
| Checkpoint save | **`mutation_state_json` only**；`CHECKPOINT_MUTATION_STATE_V2_ENABLED` default **1** |
| Resume | hydrate → `set_shadow`；resume hint 读 TMS |
| Legacy files | 删除或 shim |

---

## 3. 模块删除 / 迁移计划

### 3.1 删除或 thin-wrap

| 模块 | M5 动作 |
|------|---------|
| `context/mutation_fsm.py` | 删除；guard 逻辑迁入 `context/tms/guards.py` 或 `workflow.py` |
| `context/execution_state.py` | 删除 marker advance；**迁出** survivors 见 §3.2 |
| `context/tms/adapter.py` | 删除 `build_tms_from_legacy`, `sync_tms_from_legacy`, `mirror_tms_to_legacy` |
| `context/tms/parity.py` | 删除（或仅测试 harness） |
| `context/tms/advance.py` | 删除 `_mirror_milestone_to_legacy` |

### 3.2 从 execution_state 迁出的 survivors

| 符号 | 目标位置 | 用途 |
|------|----------|------|
| `compute_proposal_digest` | `context/tms/artifacts.py` 或 `digest.py` | proposal dedup |
| `build_resume_hint` | `context/tms/resume.py` | ReAct resume UX |
| `clear_backup_milestones` | TMS artifact helpers | re-backup flow |
| `user_requests_rebackup` | 不变或 `context/tms/resume.py` | keyword detect |

### 3.3 修改清单

| 模块 | 变更 |
|------|------|
| `tools/tool_manager.py` | FSM guard + dedup skip → TMS readers |
| `react_agent.py` | 移除 sync/mirror/export v1；checkpoint save 简化 |
| `storage/checkpoint_store.py` | API 接受仅 mutation_state；v1 参数 optional/deprecated |
| `api/agent_runner.py` | 初始 state 从 TMS hydrate only |
| `context/tms/checkpoint_hydrate.py` | 无 `mirror_tms_to_legacy` post-step |
| `context/tms/backup.py` | 移除 `legacy_execution` resolver tier（flag on/off 均 TMS → global） |
| `config/settings.py` | 移除 `TMS_ADAPTER_ENABLED`, `PARITY_STRICT`；`CHECKPOINT_MUTATION_STATE_V2_ENABLED` default 1 |
| `tools/outcome_schema.py` | 标记 legacy string parse deprecation audit |
| `scripts/check_no_legacy_imports.py` | 收紧 whitelist |

---

## 4. Guard & dedup 统一到 TMS

### 4.1 FSM guard（替代 `check_mutation_fsm_allowed`）

```python
def check_mutation_allowed(
    *,
    action: str,
    milestone: MilestoneToken | None = None,
) -> GuardResult:
    """Read TMS shadow workflow + epoch; no legacy ContextVar."""
```

| 规则 | 来源 |
|------|------|
| Workflow state transitions | 已有 `MILESTONE_TO_WORKFLOW` + shadow |
| `MUTATION_FSM_ENABLED=0` | 仍 bypass guard（compat 至 D2） |
| Reject message | 结构化 outcome（D1 已 default-on 可另 PR） |

### 4.2 Dedup skip（替代 `should_skip_tool`）

```python
def should_skip_tool_tms(
    *,
    action: str,
    args: dict | None,
    result_text: str,
) -> SkipDecision:
    """Read TMS artifacts + workflow; no marker substring advance."""
```

| 场景 | TMS 字段 |
|------|----------|
| 重复 backup | `artifacts.backup` + epoch |
| 重复 patch | `artifacts.patch_applied_paths` |
| 重复 proposal | `artifacts.proposal_digest` |
| `EXECUTION_STATE_DEDUP_ENABLED=0` | bypass（default 不变） |

**风险**：dedup 与 FSM reject 交互 — M5 需 golden resume cases 覆盖。

---

## 5. Checkpoint 写入 / 读取

### 5.1 Save（M5）

| 今天 | M5 |
|------|-----|
| export v1 + v2 | export **`export_mutation_state_for_checkpoint()` only** |
| `CHECKPOINT_MUTATION_STATE_V2_ENABLED=0` 仅 v1 | flag 移除或 deprecated；save 始终 v2 |

写入列：

- `mutation_state_json` — **required**
- `execution_state_json` — **NULL / 不再更新**
- `mutation_fsm_json` — **NULL / 不再更新**

### 5.2 Resume（M5）

优先级 **不变**（M3）：

1. `mutation_state_json` (v2)
2. v1 列 merge → TMS
3. empty TMS

变更：**hydrate 后不再调用 `mirror_tms_to_legacy()`**（PR-M5-d ✓）。

Resume 后 runtime SoT = **TMS shadow only**；v2 与 v0.9 v1-only 行均经 `hydrate_checkpoint_mutation_state()` → `set_shadow`，不依赖 legacy ContextVar 作为 guard/dedup 数据源。

### 5.3 v0.9 forward compat

| 场景 | 行为 |
|------|------|
| 旧 checkpoint 仅 v1 | hydrate 算法保留；audit `checkpoint_hydrate_source=v1` |
| 新 checkpoint 仅 v2 | 标准路径 |
| 混合行（过渡期） | v2 优先 |

---

## 6. Backup & global file（M5 边界）

M4 已完成 task-scoped SoT。M5 增量：

| 项 | M5 |
|----|-----|
| `resolve_task_backup_ref` legacy_execution tier | **删除** |
| `maybe_persist_global_backup_dual_write` | 保留至 v0.10.1 或 M5 仅 flag-off 路径 |
| `project_context.set_backup_info` | doc deprecate；无 runtime 新调用 |
| CLI 无 task_id | global file read fallback 保留 |

---

## 7. Feature flags

| Flag | M4 | M5 |
|------|-----|-----|
| `TMS_ADAPTER_ENABLED` | on/off sync | **删除** |
| `PARITY_STRICT` | parity tests | **删除** |
| `CHECKPOINT_MUTATION_STATE_V2_ENABLED` | default 0；gate react save | **M5-c 后：不再 gate runtime save**；react 始终写 v2；flag 保留至 M5-f 仅作 rollback 文档 |

**M5-c flag 语义（implemented）**

| `CHECKPOINT_MUTATION_STATE_V2_ENABLED` | 效果 |
|----------------------------------------|------|
| `0`（默认） | **不**阻止 react `_save_checkpoint_safe` 写 `mutation_state_json` |
| `1` | 同上（已无额外行为差异） |
| 读取 / hydrate | 不变 — v2 优先，v1 列 fallback |

Runtime save 路径：**仅** `react_agent._save_checkpoint_safe`（生产）。`storage.checkpoint_store.save_checkpoint` API 仍接受 v1 参数供单元测试；测试/direct call 可写 v1，react 不再写 v1。

---
| `TASK_SCOPED_BACKUP_ENABLED` | default 0 | **不变** |
| `MUTATION_FSM_ENABLED` | default 0 | **不变**（D2 改 default） |
| `EXECUTION_STATE_DEDUP_ENABLED` | default 0 | **不变**（P2） |

**Rollback**：M5 合入前 bake M4；M5 回滚需 revert commit — 无 partial flag 恢复 legacy mirror。

---

## 8. Implementation sub-PRs

| ID | 内容 | 风险 |
|----|------|------|
| **M5-a** | TMS guard + dedup readers + tool_manager 接线 | 高 |
| **M5-b** | 移除 advance legacy mirror；删 marker advance 路径 | 中 |
| **M5-c** | Checkpoint save v2-only；react_agent export 简化 | 中 |
| **M5-d** | Resume hydrate 去 mirror；resume helpers 迁移 | 高 | **done** |
| **M5-e** | Checkpoint/save legacy 写路径清理；import policy 收紧 | 中 | **done** |
| **M5-f** | 移除 runtime legacy 分支；finish 清理；测试 + release 总结 | 高 | **done** |

建议顺序：**M5-a → M5-b → M5-c → M5-d → M5-e → M5-f**（与 M0–M4 相同 incremental 策略）。

### 8.1 Temporary migration paths（M5-d 后 → M5-e/f 清理）

M5-d 之后仍保留的 legacy **运行时**调用；**不得**当作长期 SoT，须在后续 sub-PR 删除。

| 符号 / call site | 文件 | 当前用途 | 清理目标 |
|------------------|------|----------|----------|
| `_sync_tms_from_legacy_safe()` | `react_agent.py` | cancel / max-steps 保存 checkpoint **前** legacy→TMS sync | **M5-e** ✓ — 已删除 |
| `mark_mutation_fsm_done()` | `react_agent.py` | finish / plain_answer 时写 legacy FSM → DONE | **M5-f** ✓ — 已删除 |
| `_export_execution_state_for_checkpoint()` | `react_agent.py` | M5-c 前 v1 checkpoint export（**已 dead**） | **M5-e** ✓ — 已删除 |
| `_export_mutation_fsm_for_checkpoint()` | `react_agent.py` | 同上（**已 dead**） | **M5-e** ✓ — 已删除 |
| `sync_tms_from_legacy()` | `context/tms/adapter.py` | adapter 单元测试 + 上项 wrapper | **M5-e/f** — 移除运行时调用后删 adapter 符号 |
| `mirror_tms_to_legacy()` | `context/tms/adapter.py` | 单元测试；M5-d 已无 resume 调用 | **M5-f** |

**M5-f runtime cleanup（implemented）**

| 区域 | 变更 |
|------|------|
| `react_agent.py` | 无 legacy import；task start 仅 `reset_mutation_state`；re-backup 用 `clear_tms_backup_milestones` |
| `tools/tool_manager.py` | FSM guard + dedup 仅 TMS readers |
| `context/tms/resume.py` | `user_requests_rebackup`, `clear_tms_backup_milestones` |
| Hydrate compat | **不变** — `checkpoint_hydrate.py` v1/v2 读取路径保留 |
| Legacy 文件 | **未删** — `mutation_fsm.py` / `execution_state.py` / `adapter.py` 供测试与 hydrate |

Release summary: [V0.10_RELEASE_SUMMARY.md](../archive/V0.10_RELEASE_SUMMARY.md)

---

| Checkpoint 形态 | Hydrate | Runtime SoT | Legacy 依赖 |
|-----------------|---------|---------------|-------------|
| v2 only (`mutation_state_json`) | `hydrate_mutation_state_v1` → `set_shadow` | **TMS shadow** | 无 mirror；guards/dedup 读 TMS（`should_use_tms_runtime_guards()`） |
| v0.9 v1 only | `hydrate_mutation_state_from_v1_columns` → `set_shadow` | **TMS shadow** | 同上；v1 列只读 compat，不刷回 legacy |
| empty | `empty_mutation_state()` → `set_shadow` | **TMS shadow** | 无 |

---

## 9. Test plan

| ID | 场景 |
|----|------|
| T1 | FSM guard 读 TMS：乱序 apply → reject |
| T2 | Dedup skip 读 TMS：重复 backup/patch skip |
| T3 | Save checkpoint：仅 `mutation_state_json` 非空 |
| T4 | Resume v0.9 v1-only row → TMS populated；无 legacy mirror side effects |
| T5 | Resume v2 row → 与 M3/M4 行为一致 |
| T6 | Golden 24+ 全绿 |
| T7 | 无 import `context.mutation_fsm` / `context.execution_state` 于生产路径 |
| T8 | v1 hydrate + scoped backup rollback 仍指向本 task |

---

## 10. Acceptance criteria（design sign-off）

- [ ] 无运行时代码调用 `advance_mutation_fsm_on_success` / marker `update_from_tool_result`
- [ ] FSM guard + dedup skip **读 TMS**
- [ ] Checkpoint save **不再更新** v1 列
- [x] Hydrate **不**调用 `mirror_tms_to_legacy`
- [x] v0.9 checkpoint hydrate 仍工作
- [x] `497+` pytest + golden 全绿
- [x] `react_agent` / `tool_manager` 无 runtime legacy guard 分支
- [ ] 不引入 worktree / verify loop / checkpoint schema v3
- [ ] Legacy API 删除或 shim 文档化

---

## 11. 风险与缓解

| 风险 | 缓解 |
|------|------|
| Guard 迁移遗漏 call site | grep + `check_no_legacy_imports` CI |
| Resume hint 行为漂移 | 迁出 helpers 后 dedicated resume tests |
| Golden 大量更新 | M5-f 独立 PR；Mode A/B 分批 |
| CLI global backup fallback | 文档 + T8 覆盖 |
| 并发 ContextVar | 沿用 M4 thread tests |

---

## 12. 与后续 Epic 关系

```
M5 (legacy removal)
  → E0 v0.10.0 regression
  → D1 STRUCTURED_TOOL_REJECT default-on（可并行 M5 前）
  → V0 verify loop design（已 out of M5 code）
  → D2 FSM default-on (v0.10.1)
  → P2 dedup default-on assessment v2
```

---

## Changelog (design)

| Date | Status |
|------|--------|
| 2026-07-21 | Initial M5 design draft post-M4 review |
