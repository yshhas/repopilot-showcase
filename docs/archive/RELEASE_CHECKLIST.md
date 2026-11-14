# Release Checklist

> **当前版本**：见下方 **v0.10.2**；历史 checklist 保留在文末。

---

# v0.10.2 Release Checklist

> **版本**：v0.10.2 — Verification loop  
> **状态**：✅ **Ready for tag** · 2026-07-23  
> **原则**：+1 ReAct tool（`verify_change`）· 无 HTTP API 变更 · 无 auto-fix / pytest runner

## 1. 代码与测试（v0.10.2）

| 检查项 | 标准 | 状态 |
|--------|------|------|
| 默认 pytest | **515 passed, 4 deselected** | ✅ |
| `APP_VERSION = 0.10.2` | `config/settings.py` | ✅ |
| ReAct tools | **15**（含 `verify_change`） | ✅ |
| Soft gate | fail keeps PATCHED；audit `verify_change_result` | ✅ |
| Design doc | `docs/design/verification_loop.md` | ✅ |

## 2. GitHub（可选）

```powershell
git tag -a v0.10.2 -m "RepoPilot v0.10.2 — Verification loop"
git push origin v0.10.2
```

---

# v0.10.1 Release Checklist（historical）

> **版本**：v0.10.1 — Guard default-on · FSM + STR default-on · **504** pytest

---

# v0.10.0 Release Checklist（historical）

> **版本**：v0.10.0 — State Consolidation  
> **状态**：✅ **Ready for tag** · docs polish 2026-07-23  
> **原则**：无新 ReAct tool · 无 HTTP API 变更 · **无默认 flag 变更**  
> **历史**：v0.9.0 checklist 已归档于 git history / 本节下方不再混用

---

## 1. 代码与测试

| 检查项 | 命令 / 标准 | 状态 |
|--------|-------------|------|
| 默认 pytest | `python -m pytest -q` → **497 passed, 4 deselected** | ✅ collect 497/501 |
| Doc gate | `python -m pytest test_project_docs.py -q` | ✅ |
| Legacy import policy | `python scripts/check_no_legacy_imports.py` → **OK** | ✅ |
| Live smoke（manual，可选） | `LIVE_LLM_EVAL_ENABLED=1 pytest -m live_llm -v tests/live_llm/` → **4 passed** | ⏳ optional |
| Golden cases | `test_llm_golden.py` → **24** cases | ✅ |
| ReAct tools = 14 | `test_diff_security.py` react tool count | ✅ |
| 默认 flags | 见 §4 | ✅ |

---

## 2. 版本与文档一致性

| 检查项 | 文件 | 状态 |
|--------|------|------|
| `APP_VERSION = 0.10.0` | `config/settings.py` | ✅ |
| CHANGELOG `[0.10.0]` · 497 tests | `CHANGELOG.md` | ✅ |
| PROJECT_STATUS Ready for tag | `docs/PROJECT_STATUS.md` | ✅ |
| README v0.10.0 · 无坏链图片 | `README.md` | ✅ |
| SECURITY supported + **497** tests | `SECURITY.md` | ✅ |
| architecture / workflow v0.10.0 | `docs/architecture.md`, `docs/workflow.md` | ✅ |
| GITHUB_DEMO / demo.md 测试数 | `docs/GITHUB_DEMO.md`, `docs/demo.md` | ✅ |
| Release summary / audit / notes | `docs/V0.10_RELEASE_*.md`, `docs/GITHUB_RELEASE_v0.10*.md` | ✅ |
| Demo assets 目录说明 | `docs/assets/README.md`（PNG 不阻塞 tag） | ✅ |

---

## 3. v0.10.0 实现范围（已落地）

| 系列 | 摘要 |
|------|------|
| M0–M5 | TMS runtime SoT · checkpoint v2-only save · v0.9 hydrate · TMS guards/dedup readers · production path 无 legacy mutation import |
| 明确未做（本 tag） | STR/FSM/dedup **default-on** · `verify_change` · legacy 文件物理删除 · worktree isolation |

详见 [V0.10_RELEASE_SUMMARY.md](V0.10_RELEASE_SUMMARY.md) · [V0.10_RELEASE_AUDIT.md](V0.10_RELEASE_AUDIT.md)。

> **与早期 roadmap 差异**：[`V0.10_ROADMAP.md`](V0.10_ROADMAP.md) 曾规划 PR-D1（STR default-on）进 v0.10.0；**实际发布保持 defaults 不变**（以 CHANGELOG / settings 为准）。D1/D2 移至 v0.10.1。

---

## 4. 默认 flag 矩阵（本 tag 不变）

```
TMS_RUNTIME_SOT_ENABLED=0
TASK_SCOPED_BACKUP_ENABLED=0
MUTATION_FSM_ENABLED=0
EXECUTION_STATE_DEDUP_ENABLED=0
STRUCTURED_TOOL_REJECT_ENABLED=0
RAG_ENABLED=0
CHECKPOINT_MUTATION_STATE_V2_ENABLED=0   # does not gate runtime v2 save
```

**禁止混入本 tag：**

- ❌ FSM / STR / dedup default on
- ❌ 新 ReAct tool（含 `verify_change`）
- ❌ HTTP API breaking change
- ❌ 强制提交 demo PNG（可选营销资产）

---

## 5. GitHub Release（tag 时执行）

### Tag

```powershell
git tag -a v0.10.0 -m "RepoPilot v0.10.0 — State Consolidation"
git push origin v0.10.0
```

### Release Notes

使用模板：[GITHUB_RELEASE_v0.10.md](GITHUB_RELEASE_v0.10.md) · body：[GITHUB_RELEASE_v0.10_BODY.md](GITHUB_RELEASE_v0.10_BODY.md)

```powershell
gh release create v0.10.0 --title "RepoPilot v0.10.0 — State Consolidation" --notes-file docs/GITHUB_RELEASE_v0.10_BODY.md
```

### Post-tag

- [ ] 确认 GitHub Release 页面版本与测试数（497 / 4 live）
- [ ]（可选）按 [DEMO_RECORDING.md](../DEMO_RECORDING.md) 补截图到 `docs/assets/` 并更新 README 图片区
- [ ] 进入 v0.10.1：Guard/FSM default-on migration（不在本 checklist）

---

## 6. 历史：v0.9.0 Release Checklist

> tag `v0.9.0` · 424 pytest · Runtime Mutation Control · 详见 [CHANGELOG](../../CHANGELOG.md) `[0.9.0]`
