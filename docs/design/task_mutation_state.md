# TaskMutationState Design (v0.10 M0)

> **Status**: **Design · v0.10 target** · M0 (2026-07-21)  
> **Flag**: N/A（M1 引入内部模块；M5 后成为唯一 mutation runtime state）  
> **Baseline**: v0.9.0 @ `v0.9.0` · 424 pytest passed  
> **Parent**: [V0.10_ROADMAP.md](../archive/V0.10_ROADMAP.md) · Architecture Challenge Review §16  
> **Related**: [mutation_fsm.md](mutation_fsm.md) · [structured_tool_results.md](structured_tool_results.md) · [dedup_default_assessment.md](dedup_default_assessment.md) · [task_checkpoint.md](task_checkpoint.md)  
> **Out of scope (M0)**: 运行时代码 · default flag 变更 · verify_change 实现（见 [verification_loop.md](verification_loop.md) draft in V0.10 §7）

---

## English Summary

**TaskMutationState (TMS)** consolidates v0.9’s split mutation tracking into a **single persisted session record** with **three internal slices**—not one undifferentiated blob. It owns **mutation lifecycle + artifacts + idempotency epoch**; it does **not** own context budget, verification outcomes, or dedup policy logic. State advances **only** via structured `ToolOutcome.milestone` through `advance_from_outcome()`. Checkpoint `mutation_state_json` v2 is the **persistence authority**; v0.9 checkpoints hydrate via a **time-bounded** v1 compat layer (supported through v0.10.x, deprecated v0.11).

---

## 1. Design goals

| # | Goal |
|---|------|
| G1 | Replace `mutation_fsm` + `execution_state` + repo-global backup **tracking** with one task-scoped model |
| G2 | Eliminate Chinese substring milestone parsing in runtime paths |
| G3 | Checkpoint v2 = single mutation persistence blob; forward-compat v0.9 hydrate |
| G4 | Model must **extend** to concurrent tasks, API workers, and worktree isolation without redesign |
| G5 | Keep slices bounded—avoid “three states → one mega-state” anti-pattern |

### 1.1 Non-goals (M0 / v0.10.0)

| Out of scope | Notes |
|--------------|-------|
| Git worktree per task | v0.11; TMS holds `workspace_ref` placeholder |
| Distributed worker / cross-process TMS | v0.11; persistence shape stays valid |
| Dedup default-on | v0.11 after bake |
| Read/analyze tools structured outcome | stay string |
| Permanent v0.9 checkpoint support | **2 minor versions** (v0.10.x), then deprecate |

---

## 2. Boundary analysis — what belongs in TMS?

### 2.1 Architecture challenge conclusion

v0.9 的三套状态本质上是 **两个职责 + 一个错误放置的全局指针**：

| v0.9 模块 | 本质职责 | v0.10 归属 |
|-----------|----------|------------|
| `mutation_fsm` | **Ordering guard** — “现在允许调用吗？” | TMS **`WorkflowSlice`** |
| `execution_state` | **Artifact memory** — “已成功做了什么？” | TMS **`ArtifactSlice`** |
| `project_context` backup | **Git pointer** — rollback/apply 依赖 | TMS **`ArtifactSlice.backup`**（task-scoped） |
| dedup skip 逻辑 | **Policy** — 非数据 | **`DedupPolicy`** 纯函数，读 TMS，不写入 TMS |
| `budget_state` | Context 预算 | **保持独立** `ContextBudgetState` |
| verification | 改码后验证 | **独立** `VerificationSlice`（可选 sibling checkpoint 字段） |

**Dedup 不是第四套 state。** v0.9 `execution_state` 里的字段已是 dedup 所需全部数据；dedup 是 `should_skip_tool(action, args, tms)` 的策略函数。

### 2.2 TMS 内部切片（bounded aggregate）

```python
# design-only — M1 implementation target
@dataclass
class WorkflowSlice:
    """Ordering FSM — answers: is this tool call legal now?"""
    state: MutationWorkflowState      # ANALYZING … DONE
    path: MutationPath                # NONE | DIFF_FIRST | WRITE_FALLBACK
    proposal_digest: str | None       # 方案 identity；变更时 invalidate artifacts

@dataclass
class ArtifactSlice:
    """Completed mutation facts — answers: what succeeded?"""
    backup: BackupRef | None           # task-scoped Git refs
    diff_previewed_paths: list[str]
    patch_applied: bool
    patch_applied_paths: list[str]

@dataclass
class BackupRef:
    backup_branch: str
    backup_commit: str
    original_branch: str
    created_at_step: int | None = None

@dataclass
class TaskMutationState:
    """Aggregate root — persisted as mutation_state_json v2."""
    workflow: WorkflowSlice
    artifacts: ArtifactSlice
    epoch: int = 0
    # epoch: re-backup / new proposal invalidates dedup generation (replaces clear_backup_milestones ad-hoc)
```

**不包含在 TMS 内：**

```python
@dataclass
class VerificationSlice:
    """Separate concern — optional, sibling persistence."""
    last_code: str | None              # verify_passed | verify_failed | verify_skipped
    checks_run: list[str]
    failed_checks: list[str]
    at_react_step: int | None
```

| 数据 | 存放 | 理由 |
|------|------|------|
| Mutation workflow + artifacts | `TaskMutationState` | 同一 mutation session 生命周期 |
| Verification | `VerificationSlice` + `verification_state_json` | 可选步骤；失败不回滚 workflow |
| Context budget | `context_state_json`（已有） | 与 mutation 正交 |
| ReAct memory | `memory_json` | 对话权威；TMS 是结构化投影 |
| Workspace isolation | 未来 `workspace_ref` in TMS or TaskRecord | v0.11 worktree |

### 2.3 为什么 backup reference 留在 TMS 内

- `apply_patch` / `git_rollback` 需要 **与 task 绑定的** backup pointer
- Backup 是 mutation artifact，不是独立 subsystem
- v0.9 bug 根源正是 backup 放在 repo-global `last_backup.json`

**`logs/last_backup.json` 角色**：M4 后降级为 **CLI 单会话 fallback read-only**；不再作为 SoT。

---

## 3. Workflow vs Artifacts — 职责与同步规则

### 3.1 为何不能只要 WorkflowSlice

v0.9 [mutation_fsm.md §2](mutation_fsm.md#2-core-distinction-execution_state-vs-fsm) 已论证：ordering 与 “what happened” 是 **互补问题**。

- **WorkflowSlice** 是 **derived + guard** 状态，可从 artifacts 部分推导（v0.9 `derive_mutation_fsm_from_execution_state`）
- **ArtifactSlice** 是 **source of truth for completed work**（dedup / rollback / audit 依赖）

### 3.2 同步 invariant（M5 后必须成立）

| Event | WorkflowSlice | ArtifactSlice |
|-------|---------------|---------------|
| `proposal_generated` | state→PROPOSED, digest set | 若 digest 变 → **clear artifacts** |
| `diff_previewed` | state→DIFF_PREVIEWED, path→DIFF_FIRST | merge preview paths |
| `backup_created` | state→BACKED_UP, path 可能→WRITE_FALLBACK | set backup ref |
| `patch_applied` / `file_written` | state→PATCHED | patch_applied=true, paths set |
| `rollback_done` | state→BACKED_UP | **keep** backup ref；clear patch_applied |
| `epoch++` (re-backup) | backup 相关 workflow 重置 | clear backup + patch artifacts |

**Single writer rule**：仅 `advance_from_outcome()` 修改 TMS；guard 函数 **read-only**。

---

## 4. ToolOutcome — unified schema

### 4.1 Type model

```python
class ToolRejectResult(TypedDict):
    ok: Literal[False]
    code: str
    message: str
    details: dict[str, Any]

class ToolSuccessResult(TypedDict):
    ok: Literal[True]
    code: str              # stable: backup_created, patch_applied, …
    message: str           # human text for memory/CLI
    milestone: str | None  # stable token for advance_from_outcome ONLY
    details: dict[str, Any]

ToolOutcome = ToolSuccessResult | ToolRejectResult
LegacyToolReturn = str  # compat input only — never advances state directly
```

### 4.2 是否所有 mutation tool 必须返回 structured outcome？

| 阶段 | 要求 |
|------|------|
| **M2+** | 6 mutation tools **必须**在 `run_tool` 内产出 `ToolSuccessResult` 或 `ToolRejectResult` |
| **M2 compat window** | `normalize_tool_outcome(raw) -> ToolOutcome` 接受 legacy string |
| **M5** | 删除 runtime string advance；legacy parse **仅**在 `normalize_tool_outcome` 一处，emit deprecation audit |
| **Read/analyze tools** | v0.10 仍返回 `str`；不进入 `advance_from_outcome` |

### 4.3 兼容层位置（单点）

```
tool function
    → normalize_tool_outcome(raw)     # ONLY legacy string parsing site
    → advance_from_outcome(outcome)   # ONLY state mutation site
    → format_outcome_for_memory(outcome)
    → format_outcome_for_display(outcome)
    → extract_outcome_audit_fields(outcome)
```

**禁止**：

- `react_agent` 内 `"工具执行结果:\n" + str(result)`
- `advance_*` 内 substring match on `message`
- 工具外散点 parse

### 4.4 Formatter 统一出口

| Consumer | Function | Notes |
|----------|----------|-------|
| ReAct memory | `format_outcome_for_memory()` | flag on: JSON line or canonical text block |
| CLI print | `format_outcome_for_display()` | 人类可读 message |
| Audit `tool_call` | `extract_outcome_audit_fields()` | `status`, `code`, `milestone`, `reject_details` |
| SSE | 同 audit callback | 不新增 HTTP schema |

`STRUCTURED_TOOL_OUTCOME_ENABLED=1`（v0.10.0 default）控制 memory 是否 embed JSON；display 始终 message-first。

### 4.5 Milestone token registry（machine-only）

| milestone | Set by code | Advances to workflow state |
|-----------|-------------|----------------------------|
| `PROPOSED` | `proposal_generated` | PROPOSED |
| `DIFF_PREVIEWED` | `diff_previewed` | DIFF_PREVIEWED |
| `BACKED_UP` | `backup_created` | BACKED_UP |
| `PATCHED` | `patch_applied`, `file_written` | PATCHED |
| `ROLLBACK_TO_BACKUP` | `rollback_done` | BACKED_UP (workflow) |

**`MilestoneToken` 为 closed enum（M1 定义，M2 接入）；禁止自由字符串。`message` 字段永不参与 advance；audit / FSM / dedup 禁止读取 message。**

---

## 5. Migration — M1 dual-write through M5

### 5.1 Phase table

| Phase | Source of truth (reads) | Writes | Guard uses |
|-------|---------------------------|--------|------------|
| **M1** | **Legacy** (`mutation_fsm` + `execution_state`) | Dual-write both | Legacy |
| **M2** | Legacy for guard; TMS for advance-from-outcome shadow | Dual-write | Legacy |
| **M3** | Legacy guard; checkpoint exports **TMS v2** + legacy mirror | Dual-write | Legacy |
| **M4** | TMS for backup ref; legacy mirror | Dual-write | Legacy |
| **M5** | **TMS only** | TMS only | TMS |

### 5.2 M1 dual-write — mismatch policy

```
on tool success:
    legacy_advance(old_modules, raw_display)
    tms_advance(tms, normalized_outcome)

after each advance:
    if not parity_equal(legacy_export, tms_export):
        audit: mutation_state_parity_mismatch { task_id, legacy, tms, tool, step }
        if PARITY_STRICT=1 (tests): raise
        else: legacy wins — tms.force_sync_from_legacy(legacy_export)
```

| 环境 | 行为 |
|------|------|
| **pytest** | `PARITY_STRICT=1` — mismatch 即 fail |
| **runtime M1–M4** | legacy wins + TMS resync + audit |
| **M5+** | no dual-write; parity tests removed |

### 5.3 M5 compatibility layer

| 组件 | M5 处理 |
|------|---------|
| `context/mutation_fsm.py` | Thin shim → delegates to TMS.WorkflowSlice (**1 minor**, v0.10.1 删) |
| `context/execution_state.py` | Thin shim → TMS.ArtifactSlice |
| `normalize_legacy_string()` | 保留于 `result_schema.py`；audit `legacy_outcome_normalized` |
| v0.9 checkpoint hydrate | 保留至 **v0.11.0**；v0.11 起 warn + best-effort |

### 5.4 v0.9 checkpoint compat — 非永久

| Version | v1 checkpoint hydrate |
|---------|----------------------|
| v0.10.0 – v0.10.x | **Required** — full merge algorithm |
| v0.11.0 | **Deprecated** — hydrate memory + empty TMS; audit `checkpoint_v1_deprecated` |
| v0.12.0+ | May remove v1 hydrate code |

**Rationale**：永久兼容会拖住 schema evolution；2 minor 窗口足够 production 用户 resume 旧 task。

### 5.5 v1 → v2 hydrate algorithm

```python
def hydrate_mutation_state_v1(
    mutation_fsm_json: dict | None,
    execution_state_json: dict | None,
    *,
    task_id: str,
    global_backup_fallback: bool = True,
) -> TaskMutationState:
    """
    1. If either v1 blob present → build TMS from merge(execution_state, mutation_fsm)
    2. execution_state artifacts preferred for backup/patch paths
    3. mutation_fsm preferred for workflow.state/path when snapshots_compatible
    4. incompatible → workflow from fsm snapshot, artifacts from execution_state, audit mismatch
    5. backup: execution_state backup fields → else task-scoped lookup → else global file (fallback, M4-)
    """
```

---

## 6. Dedup — policy, not state

```python
def should_skip_mutation_tool(
    action: str,
    args: dict,
    tms: TaskMutationState,
    *,
    dedup_enabled: bool,
) -> ToolSuccessResult | None:
    """
    Returns structured skip outcome (code=dedup_skipped), not plain string.
    Reads TMS.ArtifactSlice + epoch only.
    """
```

| v0.9 behavior | v0.10 change |
|---------------|--------------|
| Plain string `跳过重复…` | `ToolSuccessResult{code=dedup_skipped, milestone=None}` |
| Does not advance TMS | Still does not advance |
| audit `execution_state_dedup` | Same event + `dedup_epoch` |

Re-backup：用户关键词 → `tms.epoch += 1` + clear artifact backup/patch（保留 proposal digest 可选）。

---

## 7. Verification — separate slice (cross-ref)

> Full spec: `design/verification_loop.md` (V0 PR-V0). Summary here for TMS boundary.

| Question | v0.10.0 answer |
|----------|----------------|
| verify 是 mutation workflow state 吗？ | **No** — optional `VerificationSlice`; workflow 仍 PATCHED→DONE |
| verify 失败 FSM 回退吗？ | **No** — stay PATCHED; outcome `verify_failed` |
| verify 失败阻止 DONE 吗？ | **No** (soft gate) |
| 用户主动 finish？ | `FinishResponse` / plain answer → `workflow.state=DONE`; verification optional |
| v0.10.x hard gate? | PATCHED → verify → DONE optional enforce |

`verify_change` tool **不调用** `advance_from_outcome` on workflow；更新 `VerificationSlice` only.

---

## 8. Checkpoint persistence

### 8.1 v2 checkpoint shape

```json
{
  "schema_version": 2,
  "workflow": { "state": "BACKED_UP", "path": "DIFF_FIRST", "proposal_digest": "abc…" },
  "artifacts": {
    "backup": { "backup_branch": "…", "backup_commit": "…", "original_branch": "main" },
    "diff_previewed_paths": ["a.py"],
    "patch_applied": false,
    "patch_applied_paths": []
  },
  "epoch": 0
}
```

Sibling (optional):

```json
// verification_state_json
{ "last_code": "verify_passed", "checks_run": ["syntax"], "failed_checks": [], "at_react_step": 8 }
```

### 8.2 Authority rule

| Data | Authority |
|------|-----------|
| Conversation | `memory_json` |
| Mutation session | **`mutation_state_json` v2** |
| Context budget | `context_state_json` |
| Verification | `verification_state_json` |
| v1 legacy columns | Read-only hydrate input; **not written after M5** |

---

## 9. Future extensibility

### 9.1 Multi-task concurrency (v0.10 M4)

| Concern | TMS response |
|---------|--------------|
| Per-task isolation | TMS in ContextVar keyed by `task_id` token — **already thread-safe pattern** |
| Global backup bug | `ArtifactSlice.backup` task-scoped; no cross-task write |
| Concurrent patch | **Out of scope v0.10** — document “one writer per repo” limitation |

### 9.2 API server worker化 (v0.11)

| Concern | TMS response |
|---------|--------------|
| Cross-process TMS | Checkpoint SQLite already durable; worker loads TMS on task start |
| In-memory ContextVar | Worker thread sets ContextVar from checkpoint at resume |
| SSE/confirm | Unchanged — not in TMS |

**TMS 模型成立**：持久化 blob 与进程模型无关。

### 9.3 Worktree isolation (v0.11)

Extend `TaskMutationState` or `TaskRecord`:

```python
@dataclass
class WorkspaceRef:
    kind: Literal["in_repo", "worktree", "sandbox"]
    path: str              # absolute workspace root for this task
    git_worktree: str | None
```

| Field | Purpose |
|-------|---------|
| `workspace_ref` | `REPO_ROOT` for tools when task runs in worktree |
| `ArtifactSlice.backup` | Still task-scoped; points to commits in that worktree’s repo |

**No TMS redesign required** — additive field + checkpoint v3 when needed.

### 9.4 Dedup default-on (v0.11)

`DedupPolicy` reads TMS; default-on 是 flag 变更，不是 schema 变更。

---

## 10. Module layout (M1 target)

```
context/
  task_mutation_state.py    # aggregate + advance + guard + export/import
  mutation_workflow.py      # WorkflowSlice types + check_transition (optional split)
  mutation_artifacts.py     # ArtifactSlice + BackupRef (optional split)
  verification_state.py     # VerificationSlice (V1)
  budget_state.py           # unchanged

tools/
  result_schema.py          # ToolOutcome + normalize + formatters

storage/
  checkpoint_store.py       # mutation_state_json v2 + hydrate v1
```

**M1 可先 monolith `task_mutation_state.py`，M5 前按 slice 拆文件 if needed。**

---

## 11. `run_tool` integration (target)

```
1. agent_mode block          → ToolRejectResult
2. pydantic validate         → ToolRejectResult
3. check_transition(tms)     → ToolRejectResult  (replaces mutation_fsm_check)
4. should_skip_mutation_tool → ToolSuccessResult dedup_skipped (optional)
5. tool confirm
6. tool function             → raw return
7. normalize_tool_outcome    → ToolOutcome
8. advance_from_outcome      → TMS (if success + milestone)
9. formatters → audit / return
```

---

## 12. Acceptance criteria (M0 design sign-off)

- [ ] TMS 三切片边界 documented；dedup/verify/budget 排除理由明确
- [ ] M1–M5 SoT / mismatch / compat 策略明确
- [ ] ToolOutcome 单点 compat + 单点 advance
- [ ] v0.9 hydrate 时间边界（v0.10.x yes, v0.11 deprecate）
- [ ] Concurrent / worker / worktree 扩展路径不推翻 TMS
- [ ] Milestone token registry 与 v0.9 marker 映射表完整

---

## 13. v0.9 marker → v0.10 milestone mapping (compat)

| v0.9 substring | milestone | notes |
|----------------|-----------|-------|
| `修改方案` | PROPOSED | legacy normalize only |
| diff in text | DIFF_PREVIEWED | prefer structured |
| `Git 备份完成` | BACKED_UP | |
| `Patch 应用完成` | PATCHED | |
| `文件写入完成` | PATCHED | |
| `Git 回滚完成` | ROLLBACK_TO_BACKUP | |

---

## 14. Document history

| Date | Status | Notes |
|------|--------|-------|
| 2026-07-21 | **Design · v0.10 M0** | Architecture challenge review 后首版 |
