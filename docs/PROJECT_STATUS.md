# RepoPilot 项目状态

> **当前版本**：**v0.12.0**（工程加固 · CI 全量测试 · 文档整理）  
> **基线**：v0.11.0 LLM Provider / Token Context · v0.10.2 Verification loop · [v0.10.0](archive/V0.10_RELEASE_SUMMARY.md) State Consolidation  
> **更新日期**：2026-11-14  
> **相关**：[CHANGELOG.md](../CHANGELOG.md) · [design/verification_loop.md](design/verification_loop.md) · [architecture.md](architecture.md)

---

## 阶段总结

**v0.12.0** 在 v0.11.0 基础上完成工程加固（Ruff 整改、CI 全量测试、README 重构、历史文档归档），不改变运行时行为。以下为 v0.10.2 验证闭环概要：

```
propose → confirm → backup → apply_patch → verify_change → finish
```

| 项 | 状态 |
|----|------|
| `verify_change` ReAct tool | ✅ #15 |
| Checks | `patched_files` + Python `syntax`（MVP） |
| TMS `VerificationSlice` | ✅ 写入 `mutation_state_json.verification` |
| Workflow on verify fail | **保持 PATCHED**（不自动 rollback） |
| Soft gate | ✅ 仅 PATCHED 可调用；可跳过直接 finish |
| pytest / 静态分析平台 | ❌ 不做 |

**525 pytest** 全绿（**4 deselected**；本机与 GitHub Actions 的 Python 3.11 / 3.12 矩阵均通过），`APP_VERSION=0.12.0`。

---

## 版本与里程碑

| Tag | 内容 | 状态 |
|-----|------|------|
| **v0.10.0** | TMS SoT + checkpoint v2 | ✅ |
| **v0.10.1** | FSM + STR default-on | ✅ |
| **v0.10.2** | `verify_change` soft loop | ✅ |
| **v0.11.0** | LLM Provider + token context + CI/CD + E2E | ✅ |
| **v0.12.0** | Engineering hardening + full CI + docs | ✅ |
| **v1.x** | dedup bake / isolation / … | ⏳ |

---

## 测试与验证

| 类型 | 结果 |
|------|------|
| `python -m pytest -q` | **525 passed, 4 deselected**（本机 + GitHub Actions 3.11/3.12） |
| Golden | **26** cases（含 2 个 verify_change 场景） |
| Legacy import policy | OK |

---

## 发布状态

| 项 | 状态 |
|---|---|
| Tag | v0.12.0（公开展示仓库首个版本） |
| GitHub Release | v0.12.0（公开时创建） |
| 历史发布文档 | 已归档至 [`docs/archive/`](archive/) |

---

## 已知限制

| 类别 | 说明 |
|------|------|
| Verify soft | Prompt 引导；仍可跳过 verify 直接 finish |
| No pytest check | MVP 不含测试运行器（避免误报） |
| Dedup | 默认 off |
| Resume | 仅 HTTP API，CLI 不支持 |
| RAG | 默认关闭；默认 embedding 为 mock |
| Docker | compose 将仓库只读挂载，full 模式写入需改挂载 |
