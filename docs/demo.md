# Demo 指南

> **版本**：v0.8.0  
> **依据**：当前代码库实际可运行流程  
> **相关文档**：[GITHUB_DEMO.md](GITHUB_DEMO.md) · [工作流程](workflow.md) · [架构设计](architecture.md) · [Demo 录制手册](DEMO_RECORDING.md)

**GitHub 预览资产**（PNG / 可选 GIF）：[assets/](assets/) · 5 分钟路径见 **[GITHUB_DEMO.md](GITHUB_DEMO.md)**

本文提供可复现 Demo：**只读分析**、**修改闭环**、**可观测性**、**HTTP API**、**Docker**。按顺序执行约 10～15 分钟。

---

## 0. 前置条件

### 环境

- Python 3.10+
- Git 已安装并在 PATH 中
- DeepSeek API Key

### 安装与配置

```powershell
cd repopilot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

创建 `.env`：

```env
DEEPSEEK_API_KEY=your_key_here
```

### Git 初始化（修改 Demo 必须）

仓库需至少有一个 commit，否则 `git_create_backup` 无法工作：

```powershell
git init
git add .
git commit -m "initial commit"
```

> 若已有 Git 历史，跳过此步。

### 验证环境

```powershell
python -c "from tools.tool_manager import run_tool; print(run_tool('calculator', {'a': 1, 'b': 2}))"
# 预期输出: 3

python -c "from tools.tool_manager import run_tool; print(run_tool('git_status', {}))"
# 预期: 显示当前分支与 commit 信息
```

---

## Demo A：只读分析（约 3 分钟）

**目标**：展示 Agent 读取与分析仓库，不涉及文件修改。

### 启动

```powershell
python react_agent.py
```

### 输入

```
列出 tools 目录下的 Python 文件
```

### 预期行为

1. Agent 返回 JSON 调用 `list_repo_files`
2. 终端打印 `AI输出:` 和 `工具返回:`
3. Agent 再次调用 LLM，返回 `finish` 或自然语言总结
4. 终端打印 `回答:` 包含文件列表

### 预期工具链

```
list_repo_files → (可选 read_repo_file) → finish
```

### 验证审计

会话期间终端不会显示 `task_id`，可从审计日志查找：

```powershell
Get-Content logs\audit.jsonl -Encoding utf8 | Select-Object -Last 5
```

应看到 `react_step`（task_start、tool_request、tool_result、finish）和 `tool_call` 事件。

---

## Demo B：修改闭环（约 5～8 分钟）

**目标**：完整演示「方案 → 确认 → 备份 → 写入 → 总结」流程。

### 准备

确认项目根目录存在 `test.txt`（仓库中已有此文件）。若不存在：

```powershell
echo "original content" > test.txt
git add test.txt
git commit -m "add test.txt for demo"
```

### 第 1 轮：请求修改（出方案）

```
帮我在 test.txt 写入一行 MVP demo marker，先出修改方案，不要直接写入
```

**预期**：

- Agent 可能先 `read_repo_file` 读取当前内容
- 调用 `propose_code_changes` 输出结构化方案
- Agent 用自然语言总结方案，**等待你确认**
- **不会**在此轮调用 `git_create_backup` 或 `write_repo_file`

### 第 2 轮：确认执行

```
确认执行
```

**预期**：

1. Agent 调用 `git_create_backup`
2. 终端显示备份分支名（如 `agent-backup/20260719-xxxxxx`）
3. Agent 调用 `write_repo_file`
4. 终端弹出确认：

   ```
   === 工具执行确认 ===
   工具: write_repo_file
   参数: {'path': 'test.txt', 'content': '...'}
   确认执行？输入 y 继续，其他键取消:
   ```

5. 输入 `y`，写入成功
6. Agent 返回 `finish` 总结

### 第 3 轮（可选）：验证写入

```
读取 test.txt 的内容
```

**预期**：Agent 通过 `read_repo_file` 返回更新后的内容。

### 验证 Git 备份

```powershell
git branch | Select-String "agent-backup"
Get-Content logs\last_backup.json -Encoding utf8
```

`last_backup.json` 应包含 `backup_branch`、`backup_commit`、`original_branch`。

---

## Demo C：可观测性（约 2 分钟）

**目标**：展示任务记录、审计报告、原始 JSONL。

### 获取 task_id

Demo B 会话的 `task_id` 在审计日志中：

```powershell
Get-Content logs\audit.jsonl -Encoding utf8 | Select-Object -Last 20 | Select-String "task_id"
```

或查看 SQLite 最近任务：

```powershell
python -c "from storage.task_store import list_tasks; import pprint; pprint.pp(list_tasks(3))"
```

记下 `task_id`（8 位 hex，如 `a1b2c3d4`）。

### 生成任务审计报告

```powershell
python -m audit.task_report YOUR_TASK_ID
```

**预期输出包含**：

```
===== 任务审计摘要 =====
任务 ID: ...
状态: completed
问题: ...
回答: ...

--- 事件统计 ---
react_step: ...
tool_call: ...

--- ReAct 流程 ---
1. [时间] 任务开始: ...
...

--- 工具调用 ---
- propose_code_changes: 调用 1 次, ...
- git_create_backup: 调用 1 次, ...
- write_repo_file: 调用 1 次, ...

--- 写入 / Git / 确认 ---
- [时间] Git 备份: agent-backup/...
- [时间] 覆盖文件 test.txt ...
- [时间] 写入确认 (已确认): write_repo_file

===== 报告结束 =====
```

### 查看原始审计片段

```powershell
Get-Content logs\audit.jsonl -Encoding utf8 | Select-Object -Last 10
```

---

## Demo D：回滚（约 1 分钟，可选）

**目标**：演示 Git 回滚恢复。

### 在 CLI 中输入

```
回滚刚才对 test.txt 的修改
```

**预期**：

- Agent 调用 `git_rollback`
- 终端显示回滚成功
- `test.txt` 恢复为备份前内容

### 验证

```powershell
Get-Content test.txt
python -m audit.task_report YOUR_TASK_ID
```

报告中应出现 `Git 回滚` 事件。

---

## Demo E：HTTP API 只读模式（约 3 分钟）

**目标**：通过 API 提交只读任务，验证 AGENT_MODE 与 C3–C6 端点。

### 启动 API

```powershell
python -m api.main
```

### 提交只读任务

```powershell
curl -X POST http://127.0.0.1:8000/tasks `
  -H "Content-Type: application/json" `
  -d "{\"question\": \"列出 tools 目录下的 Python 文件\", \"mode\": \"readonly\"}"
```

记下返回的 `task_id`。

### 查询与报告

```powershell
curl http://127.0.0.1:8000/tasks/YOUR_TASK_ID
curl http://127.0.0.1:8000/tasks/YOUR_TASK_ID/report
curl http://127.0.0.1:8000/health
```

**预期**：`health` 含 `agent_mode`；任务 `status` 最终为 `completed`；报告含工具调用；readonly 模式下不会出现 `write_repo_file`。

### 自动化冒烟（无需手动 curl）

```powershell
python scripts/api_smoke_test.py
```

---

## Demo F：Docker Compose（约 2 分钟）

**目标**：一键容器化启动 API 并验证健康检查。

### 前置

- 已安装 Docker Desktop / Docker Engine + Compose v2
- 项目根目录已有 `.env`（含 `DEEPSEEK_API_KEY`）

### 启动与验证

```powershell
docker compose up --build -d
python scripts/api_smoke_test.py
# 或仅健康检查:
python scripts/api_smoke_test.py --health-only
docker compose down
```

**说明**：镜像构建时会 `git init` 并提交 baseline，使容器内 `git_create_backup` 可用（与宿主机 `.git` 独立）。

---

## Demo 输出参考

### calculator 工具调用（环境验证）

```
请输入: 计算 3 加 5

AI输出: {"action": "calculator", "args": {"a": 3, "b": 5}}

工具返回: 8

AI输出: {"action": "finish", "answer": "3 加 5 等于 8。"}

回答: 3 加 5 等于 8。
```

### write_repo_file 确认拦截

若输入非 `y`：

```
确认执行？输入 y 继续，其他键取消: n

工具返回: 用户已取消执行工具: write_repo_file
```

Agent 应随后询问是否回滚或重新尝试。

---

## 常见问题

### Q: git_create_backup 报「尚无 commit」

执行 Git 初始化（见前置条件），至少完成一次 `git commit`。

### Q: propose_code_changes 返回解析失败

LLM 输出格式不符合 JSON 要求。可重试或缩小任务范围，指定 `target_files`。

### Q: write_repo_file 报「文件类型不在可写范围内」

`.json` 等扩展名不在 `WRITABLE_EXTENSIONS` 中。改用 `.txt`、`.py` 等允许的类型。

### Q: 找不到 task_id

每个 CLI 会话启动时分配一个 ID，同会话所有轮次共用。从 `list_tasks()` 或 `audit.jsonl` 最近记录中获取。

### Q: Demo 中 Agent 跳过方案直接写入

这是 LLM 行为偏差。可明确提示「先出方案，不要直接写入」，或新开一轮会话重试。

---

## 自动化测试（无需 LLM）

```powershell
python -m pytest -q
```

预期：**525 passed, 4 deselected**（`--ignore=tests` 的 CI 口径为 **505 passed**；默认排除 `@pytest.mark.live_llm`；含 API、RAG、TMS/FSM、`verify_change`、golden 等）

Live smoke（opt-in，需 API key）：

```powershell
$env:LIVE_LLM_EVAL_ENABLED = "1"
python -m pytest -m live_llm -v tests/live_llm/test_live_smoke.py
```

---

## Demo 检查清单

| 步骤 | Demo | 验证方式 |
|------|------|----------|
| **Demo 资产** | 可选 | PNG **不阻塞** v0.10.0 tag；录制后提交 `docs/assets/` — 见 [DEMO_RECORDING.md](DEMO_RECORDING.md) · [assets/README.md](assets/README.md) |
| 只读列文件 | A | 终端回答含 tools/*.py |
| 结构化方案 | B 第 1 轮 | 输出「修改方案」文本 |
| 流程级确认 | B 第 2 轮 | 用户输入「确认执行」后才 backup |
| Git 备份 | B 第 2 轮 | `last_backup.json` 存在 |
| 工具级 y/n | B 第 2 轮 | 终端弹出确认，输入 y |
| 文件写入 | B 第 2 轮 | test.txt 内容已更新 |
| 任务记录 | C | `list_tasks()` 有记录 |
| 审计报告 | C | `task_report` 含完整章节 |
| Git 回滚 | D | test.txt 恢复 + 报告含 rollback |
| API 只读 | E | smoke test 6/6 或 curl 任务 completed |
| Docker 启动 | F | `GET /health` 返回 ok |
