# Demo 录制手册

> **用途**：按固定分镜录制 GitHub 展示资产（P0）  
> **依据**：[demo.md](demo.md) Demo A / B / C  
> **产出目录**：[assets/](assets/)

---

## 1. 前置检查

### 环境

- Python 3.10+，已 `pip install -r requirements.txt`
- Git 已安装，仓库 **至少有一个 commit**
- `.env` 含有效 `DEEPSEEK_API_KEY`

### 快速自检

```powershell
python -c "from tools.tool_manager import run_tool; print(run_tool('calculator', {'a': 1, 'b': 2}))"
python -c "from tools.tool_manager import run_tool; print(run_tool('git_status', {}))"
```

### Demo 文件

确认项目根目录存在 `test.txt`（Demo B 写入目标）。若不存在：

```powershell
echo "original content" > test.txt
git add test.txt
git commit -m "add test.txt for demo"
```

### 录制前清理（可选）

- 关闭无关窗口与通知
- 终端：深色主题，字号 ≥ 14
- 新开会话或清空终端，避免泄露 `.env` / API Key

---

## 2. 推荐工具（Windows）

| 工具 | 用途 |
|------|------|
| [ScreenToGif](https://www.screentogif.com/) | 录终端 → 导出 GIF（**推荐**） |
| OBS Studio | 录 MP4，再用 ffmpeg / ScreenToGif 转 GIF |
| 系统截图 | Win+Shift+S → 保存 PNG |

**GIF 压缩**（可选）：ScreenToGif 导出时降帧率；或使用 [gifsicle](https://www.lcdf.org/gifsicle/)：

```powershell
gifsicle -O3 --lossy=80 -o docs/assets/demo-cli-report.gif docs/assets/demo-cli-report.raw.gif
```

---

## 3. 分镜脚本

按 Demo A / B / C 分别录制，导出为 **三个 GIF**（用于本地演示或 Release 附件；公开仓库 README 仅保留一张真实终端截图）。剪辑时对 LLM 等待段落 **2x–3x 加速** 或跳切。

| 产出文件 | Demo | 操作 |
|----------|------|------|
| **demo-cli-read.gif** | **A 只读** | `python react_agent.py` |
| | | 输入：`列出 tools 目录下的 Python 文件` |
| | | 等待：出现 `list_repo_files` → `工具返回` → `回答` |
| **demo-cli-modify.gif** | **B 改码** | 输入：`帮我在 test.txt 写入一行 MVP demo marker，先出方案，不要直接写入` |
| | | 等待：`propose_code_changes` 方案输出 |
| | | 输入：`确认执行` |
| | | 等待：`git_create_backup` → `write_repo_file` 确认提示 |
| | | 输入：`y` |
| | | 等待：`finish` 总结 |
| **demo-cli-report.gif** | **C 可观测** | `exit` 退出 CLI |
| | | 从 `logs\audit.jsonl` 或 `list_tasks()` 获取 `task_id` |
| | | `python -m audit.task_report YOUR_TASK_ID` |
| | | 滚动展示报告中的工具调用 / Git 备份 / 写入确认章节 |
| **（可选）** | **E 一瞥** | 浏览器打开 `http://127.0.0.1:8000/docs` 或 `curl http://127.0.0.1:8000/health`（需先 `python -m api.main`）→ 截图为 `demo-api-health.png` |

**不纳入 CLI GIF**：Demo D 回滚、Demo F Docker（见 [demo.md](demo.md) 文字说明即可）。

---

## 4. 产出文件

录制完成后保存到 `docs/assets/`：

```
docs/assets/demo-cli-read.gif       # Demo A — 只读分析
docs/assets/demo-cli-modify.gif     # Demo B — 改码闭环
docs/assets/demo-cli-report.gif     # Demo C — 任务报告
docs/assets/demo-audit-report.jpg   # 建议 — 报告关键段落静帧
docs/assets/demo-api-health.png     # 可选 — API 健康检查或 /docs
```

### 截图建议

- **demo-audit-report.jpg**：`task_report` 输出中含「工具调用」「Git 备份」「写入确认」的窗口
- **demo-api-health.png**：`GET /health` JSON 含 `status`、`version`、`agent_mode`

---

## 5. 提交前检查

- [ ] GIF 体积 &lt; 8 MB（过大则降帧 / 裁边 / 压缩）
- [ ] 画面中无 API Key、`.env` 路径、个人隐私
- [ ] 文件名与 [assets/README.md](assets/README.md) 的清单一致
- [ ] 本地打开 README 预览，其中引用的图片可正常显示
- [ ] `python -m pytest test_project_docs.py -v` 通过

---

## 6. 常见问题

### Agent 跳过方案直接写入

新开一轮会话，强调「先出修改方案，不要直接写入」；或缩小任务为仅修改 `test.txt`。

### git_create_backup 报「尚无 commit」

执行 `git init && git add . && git commit -m "initial commit"`。

### GIF 在 GitHub 不显示

- 确认文件已 push 到默认分支
- 路径为相对仓库根：`docs/assets/demo-cli-read.gif` 等
- 单 GIF 建议 &lt; 10 MB 且格式为 GIF（`demo-cli-report.gif` 若过大需压缩，见 §2）

---

## 7. 相关文档

- [demo.md](demo.md) — 完整 Demo A–F 步骤
- [assets/README.md](assets/README.md) — 资产清单与状态
- [PROJECT_STATUS.md](PROJECT_STATUS.md) — P0 验收标准
