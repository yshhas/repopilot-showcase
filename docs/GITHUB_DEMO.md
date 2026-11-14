# GitHub 最小 Demo（5 分钟）

> **版本**：v0.10.2  
> **目标**：在 GitHub 上快速展示 RepoPilot 核心价值 — ReAct 工具编排、Git 安全网、全链路审计、TMS 状态收敛。  
> **完整脚本**：[demo.md](demo.md) · **资产目录**：[assets/](assets/)（截图按 [DEMO_RECORDING.md](DEMO_RECORDING.md) 录制后提交）

---

## 价值链路（推荐对外讲述）

```
读取 / 搜索 → 结构化方案 → 用户确认 → Diff 预览 → Git 备份 → apply_patch (y/n) → 审计报告
```

区别于普通 ChatBot：**工具可验证、写入需确认、Git 可回滚、全程可审计**。

---

## 前置（1 分钟）

```powershell
cd repopilot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # 填入 DEEPSEEK_API_KEY
git init && git add . && git commit -m "initial commit"   # 修改 Demo 必须
python react_agent.py
```

> Demo B 写入目标为仓库根目录 **`test.txt`**（仓库中已有）。若缺失：`echo "original content" > test.txt`，然后 `git add test.txt && git commit -m "add test.txt for demo"`。

---

## Demo A — 只读分析（~1 分钟）

**用户输入：**

```
列出 tools 目录下的 Python 文件
```

**预期 Tool 链：**

| 步骤 | 典型 tool |
|------|-----------|
| 1 | `list_repo_files` |
| 2 | （可选）`read_repo_file` / `search_in_repo` |
| 3 | finish / 自然语言总结 |

**展示要点：** ReAct JSON 工具调用、readonly 无 mutation、终端 `AI输出` / `工具返回`。

> 截图（可选）：录制后提交 `docs/assets/demo-cli-read.png` — 见 [DEMO_RECORDING.md](DEMO_RECORDING.md)

---

## Demo B — 改码闭环（~2 分钟）

**第 1 轮 — 出方案：**

```
帮我在 test.txt 末尾增加一行 "# RepoPilot demo"，先出方案不要写入
```

**预期：** `propose_code_changes` → 结构化方案 → 等待确认（不 apply）。

**第 2 轮 — 确认执行：**

```
确认执行
```

**预期 Tool 链（推荐 diff-first）：**

```
generate_unified_diff → git_create_backup → apply_patch (y/n) → finish
```

**展示要点：** diff 预览、备份分支、`apply_patch` 人工确认。

> 截图（可选）：`docs/assets/demo-cli-modify.png`

---

## Demo C — 审计报告（~1 分钟）

任务完成后，使用 CLI 或 HTTP 查看报告：

```powershell
python -m audit.task_report YOUR_TASK_ID
```

或：

```powershell
curl http://127.0.0.1:8000/tasks/YOUR_TASK_ID/report
```

**报告应包含：** 任务 ID、状态、tool 调用摘要、diff/patch 事件（无 raw diff 正文）。

> 截图（可选）：`docs/assets/demo-cli-report.png` · `demo-audit-report.png`

---

## Demo D — HTTP API（可选，~1 分钟）

```powershell
python -m api.main
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/tasks -H "Content-Type: application/json" -d "{\"question\": \"列出 tools 目录\", \"mode\": \"readonly\"}"
```

> 截图（可选）：`docs/assets/demo-api-health.png` · 或运行 `python scripts/api_smoke_test.py --health-only`

---

## Demo E — RAG 增强检索（可选，无 LLM 成本）

Demo A–D **不要求** 开启 RAG。若要展示 opt-in hybrid search（`grep` + 可选 `symbol` / `semantic` 合并）：

```powershell
$env:RAG_ENABLED = "1"
python -m rag.build
python -c "from tools.tool_manager import run_tool; print(run_tool('search_in_repo', {'keyword': 'HybridRetriever', 'extensions': '.py', 'max_results': 5}))"
```

**预期：** 输出含 `检索模式: hybrid`；与 `$env:RAG_ENABLED = "0"` 对比可见差异。

完整步骤（含 RAG off 对比、audit 检查、可选 propose expand）：**[RAG_DEMO.md](RAG_DEMO.md)**。

> 注意：`python -m rag.build` 不会自动读取 `.env`；需在 shell 中设置 `$env:RAG_ENABLED = "1"`。

---

## v0.8 能力说明（Demo 可选提及）

| 能力 | 默认 | 说明 |
|------|------|------|
| `EXECUTION_STATE_DEDUP_ENABLED` | `0` | resume 防重复 backup/apply（opt-in） |
| Live LLM smoke | opt-in | `LIVE_LLM_EVAL_ENABLED=1 pytest -m live_llm` |
| `RAG_ENABLED` | `0` | v0.6/v0.7 兼容；启用与验证见 **[RAG_DEMO.md](RAG_DEMO.md)** |

Demo 脚本 **不要求** 开启上述 flag；保持默认即可复现 v0.7 行为 + v0.8 文档同步。

---

## 验证清单

- [ ] 只读 Demo 无 `apply_patch` / `git_create_backup`
- [ ] 改码 Demo 出现 y/n 确认
- [ ] `logs/audit.jsonl` 有新事件
- [ ] task report 非空且含 task_id
- [ ] `python -m pytest -q` → 525 passed, 4 deselected（CI 口径 `--ignore=tests` → 505 passed）
