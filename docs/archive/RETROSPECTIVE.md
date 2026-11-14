# RepoPilot 项目复盘（v0.3.0 阶段总结 · v0.4.0 附录）

> **Release**：`v0.3.0` · **Tag**：`v0.3.0` → `b26b7b9`  
> **日期**：2026-07-19（正文）· **v0.4.0 附录**：2026-07-20  
> **用途**：后续路线评估、求职包装、是否继续开发的决策依据  
> **v0.4.0**：候选分支 `feature/unified-diff-mvp` — **14** ReAct 工具 · **150** pytest · Unified Diff MVP（S1–S8）· 人工验收通过  
> **相关**：[PROJECT_STATUS.md](../PROJECT_STATUS.md) · [CHANGELOG.md](../../CHANGELOG.md) · [architecture.md](../architecture.md)

---

## 1. 项目整体定位

### 1.1 解决什么问题

RepoPilot 针对 **「在企业代码仓库里安全地读、分析、提出改码方案、在人工确认后受控写入、并可回滚、可追溯」** 这一完整研发闭环，而不是回答泛化问题或单次 tool call。

核心场景：

- 开发者/平台方希望 Agent **在仓库边界内** 工作，而不是任意读文件、任意改代码
- 改码前需要 **结构化方案 + 人工确认**，而不是 LLM 直接写盘
- 写入前需要 **Git 备份**，失败可 **回滚**
- 每次任务需要 **审计记录 + 任务报告**，满足「谁做了什么、何时做的」

一句话：**把「AI 改代码」从事故高发点，变成有安全网、有流程、有证据链的工程能力。**

### 1.2 与普通 ChatBot / Tool Calling Agent 的区别

| 维度 | 普通 ChatBot | 典型 Tool Agent | **RepoPilot** |
|------|-------------|-----------------|-------------|
| 目标 | 对话/问答 | 调用工具完成任务 | **企业仓库研发闭环** |
| 改码方式 | 无或粘贴代码块 | 常直接 write/edit | **propose → 确认 → backup → write** |
| 安全边界 | 无 | 弱或 ad-hoc | **path_guard + 扩展名白名单 + 敏感路径拒绝 + 脱敏** |
| 人工确认 | 无 | 少见 | **双重确认**（流程级 + write y/n / API confirm） |
| 回滚 | 无 | 少见 | **Git backup branch + reset --hard** |
| 可观测 | 聊天记录 | 部分日志 | **JSONL 审计 + SQLite 任务 + task_report + SSE** |
| 入口 | Web/CLI | 多为单一入口 | **CLI + HTTP API 双入口，共享内核** |
| 模式 | 单一能力 | 单一能力 | **full / readonly 运行时切换** |

差异化不在「工具多」，而在 **流程工程化 + 安全网 + 审计链** 三者组合。

### 1.3 适合的展示方向

| 场景 | 适合度 | 怎么讲 |
|------|--------|--------|
| **GitHub portfolio** | ★★★★★ | 版本线清晰（v0.1→v0.3）、CI/Docker、文档齐全；P0 GIF/PNG 已嵌入 README |
| **简历项目** | ★★★★★ | ReAct Agent、工具注册表、Git 安全网、FastAPI 服务化、审计系统、87 测试 |
| **面试深挖** | ★★★★☆ | 架构分层、confirm 双通道、ContextVar、AGENT_MODE 过滤、redaction 设计 |
| **生产部署叙事** | ★★★☆☆ | Docker + 可选 API Key；无 OAuth/K8s/多租户，需诚实说明边界 |
| **学术/论文型 Agent 研究** | ★★☆☆☆ | 无 eval benchmark、无 multi-agent、无 RAG 融合 |

**最佳叙事**：「**工程型代码 Agent MVP** — 把 LLM 能力包进可审计、可回滚、可服务化的研发流程里。」

---

## 2. 完整版本演进

### v0.1.0 — CLI MVP（C1–C2）

| 项 | 内容 |
|----|------|
| **背景** | 验证「企业仓库 Agent」核心闭环是否可行，先不做 HTTP |
| **实现** | ReAct CLI、`react_agent.py`、12 个 ReAct 工具、path_guard、safe_write、Git backup/rollback、JSONL 审计、SQLite 任务、task_report |
| **技术点** | Pydantic 工具参数、DeepSeek LLM、ReAct 循环、双重确认（流程 + y/n） |
| **新增能力** | 读仓库 → 方案 → 确认 → 备份 → 写入 → 审计 → 报告 → 回滚 |
| **设计原因** | 先证明 **闭环故事** 成立，避免过早做 API/工程化分散精力；33 pytest 覆盖核心模块 |

### v0.2.0 — HTTP API（C3–C6）

| 项 | 内容 |
|----|------|
| **背景** | CLI 不足以展示「服务化集成」；需要 REST + 异步任务 + 实时事件 |
| **实现** | FastAPI：`/health`、`/tasks` CRUD、`POST /tasks` 后台线程、SSE stream、report、API confirm |
| **技术点** | `agent_runner` 线程调度、ContextVar 注入 confirm/stream 回调、TestClient 集成测试 |
| **新增能力** | 远程提交任务、SSE 观测、HTTP 层写确认（替代 CLI y/n） |
| **设计原因** | **双入口共享 `react_agent()`**，不 fork 两套 Agent 逻辑；API confirm 与 CLI confirm 语义对齐 |
| **测试** | 53 → 66 pytest（+20 API 相关） |

### v0.2.1 — AGENT_MODE（C7）

| 项 | 内容 |
|----|------|
| **背景** | 展示/集成场景需要「只分析不改码」模式 |
| **实现** | `full` / `readonly`；env + API per-task override；动态 system prompt；SQLite 持久化 mode |
| **技术点** | `config/agent_mode.py`、`run_tool` 层拦截、`build_system_prompt(mode)` |
| **新增能力** | readonly 可 propose 但不可 backup/write/rollback |
| **设计原因** | 比「删工具」更干净 — 统一注册表 + 运行时过滤，审计可记录模式 |

### v0.2.2 — 工程化 C8（CI + Docker）

| 项 | 内容 |
|----|------|
| **背景** | v0.2.1 功能完整但 **可复现性不足**；Docker 仅静态审查 |
| **实现** | GitHub Actions（pytest + docker job）、Dockerfile git baseline、lazy OpenAI client |
| **技术点** | `docker compose build/up` → health wait → smoke test；镜像内 `git init` baseline |
| **新增能力** | 一键容器启动、CI 实机验证闭环 |
| **设计原因** | 「能跑」比「能 demo 一次」更重要；patch 版本，不扩 Agent 功能 |
| **CI 历史** | 早期失败（import 时 init OpenAI）→ lazy client 修复 → 后续 stable |

### v0.3.0 — 展示与服务化（P1/P2 + P0 文档）

| 项 | 内容 |
|----|------|
| **背景** | 功能/工程已完整，缺 **安全叙事、HTTP 可部署感、GitHub 首屏** |
| **实现** | P1 `security/redaction.py`；P2 `api/auth.py`；P0 `DEMO_RECORDING.md` + assets 结构 |
| **技术点** | 审计/读取链 redact；可选 `API_KEY` + `X-API-Key`；空白 key = 未启用 |
| **新增能力** | 内容脱敏、HTTP 简易鉴权、Demo 录制手册 |
| **设计原因** | **不扩 ReAct/工具** — 投入产出比最高的是「包装已有能力」；P0 GIF 不阻塞 release |
| **测试** | 66 → **87**（+11 P1，+10 P2） |

---

## 3. 当前完整架构

### 3.1 入口层

| 入口 | 模块 | 行为 |
|------|------|------|
| CLI | `react_agent.py` | 多轮会话、共享 `task_id`、终端 y/n 确认 |
| HTTP | `api/main.py` | FastAPI 路由、middleware（API Key） |
| 调度 | `api/agent_runner.py` | 后台线程跑 `react_agent()`，注入 API confirm + SSE |
| Docker | `docker-compose.yml` | 容器化 uvicorn，挂载 logs/database |

### 3.2 Agent 核心 + ReAct 流程

```
用户输入 → memory 追加 → ask_ai (DeepSeek) → parse_agent_response
  → 纯文本/finish：返回，update_task completed
  → ToolCall：run_tool → 结果追加 memory → 步数+1 → 循环（max 20）
```

- CLI：**会话级 task_id**；API：**每 POST 一 task**
- 步数超限 → failed + `max_steps_reached` 审计

### 3.3 LLM 层

- **模型**：DeepSeek（OpenAI 兼容 client，lazy init）
- **Prompt**：`build_system_prompt(mode)` — 工具说明、改码流程、readonly 约束
- **解析**：`schemas.py` — JSON / markdown 块 / 混合文本 → `ToolCall` | `FinishResponse` | `str`

### 3.4 Tool 系统（ReAct 工具 · v0.3 时为 12，v0.4 增至 14）

| 类别 | 工具（v0.3 基线） |
|------|------|
| 读/分析 | `list_repo_files`, `read_repo_file`, `search_in_repo`, `analyze_repo_structure`, `find_file_dependencies` |
| 改码流程 | `propose_code_changes`, `git_status`, `git_create_backup`, `write_repo_file`, `git_rollback` |
|  utility | `summarizer`, `calculator` |

**v0.4.0 新增**：`generate_unified_diff`（只读预览）、`apply_patch`（单文件 git apply；推荐路径）。`write_repo_file` **保留**为 fallback。

- 统一 `tools/tool_manager.py` → `run_tool(name, args)`，Pydantic 校验
- `AGENT_MODE` 过滤 readonly 禁止项；遗留 `file_reader`/`pdf_reader` 不暴露 ReAct

### 3.5 安全机制

| 层 | 机制 |
|----|------|
| 路径 | `path_guard` — REPO_ROOT 边界、IGNORE_DIRS、BLOCKED_FILE_NAMES/SUFFIXES |
| 读取 | 拒绝 `.env`/credentials/*.pem；允许文件 **内容 redact**（v0.3.0） |
| 写入 | `safe_write` — 扩展名白名单（无 `.json`）、大小限制、不自动建目录 |
| 确认 | CLI y/n；API confirm + SSE |
| HTTP | 可选 `API_KEY` + `X-API-Key`（`/health` 豁免） |
| Git | backup 分支；rollback `git reset --hard` |

### 3.6 审计系统

- JSONL `logs/audit.jsonl` — tool_call、react_step、write、git、confirm；**v0.4** 增加 `diff_preview`、`patch_apply`（摘要，无 raw diff）
- 脱敏：redact_data + 长度截断
- SSE 实时推送；`task_report` Markdown 摘要

### 3.7 数据存储

| 存储 | 用途 |
|------|------|
| SQLite `database/tasks.db` | 任务元数据、agent_mode |
| JSONL | append-only 审计 |
| `logs/last_backup.json` | 跨进程 Git 备份状态（仅最近一次） |

### 3.8 API 层

8 个业务端点 + `/health`；异步任务 + SSE + report + confirm + 可选鉴权。

### 3.9 CI/CD

- **test job**：Python 3.12，`pytest -v`（87）
- **docker job**：build → up → health → smoke（无需 API_KEY）

### 3.10 Docker

Python 3.12-slim + git baseline；卷挂载 logs/database；CI 实机验证。

---

## 4. 已实现能力清单

### Agent 能力

- [x] ReAct 多轮推理（max 20 步）、CLI memory
- [x] AGENT_MODE full/readonly、动态 prompt
- [ ] unified diff / patch、multi-agent、LLM eval

### 工具与改码

- [x] 12 ReAct 工具、propose → confirm → backup → write → rollback
- [x] 整文件覆盖（非 diff）

### 安全与服务化

- [x] 路径边界、敏感文件拒绝、读取/审计脱敏
- [x] 双重确认、可选 API Key
- [x] FastAPI + SSE + Docker + smoke test

### 工程化

- [x] **150** pytest（v0.4.0 候选；v0.3.0 时点为 87）、CI 双 job、CHANGELOG v0.1→v0.4
- [x] architecture / workflow / demo / PROJECT_STATUS 文档
- [x] P0 GIF/截图（已完成，见 `docs/assets/`）

---

## 5. 测试和质量情况

### 5.1 测试分布（87 passed）

| 类别 | 代表文件 |
|------|----------|
| 解析/方案 | `test_parse_agent_response`, `test_change_proposal` |
| 安全/脱敏 | `test_file_reader_security`, `test_redaction` |
| 备份/Git | `test_backup_persistence` |
| ReAct/Prompt | `test_react_max_steps`, `test_llm_prompt` |
| 任务/报告 | `test_task_store`, `test_task_report` |
| API C3–C6 | `test_api_c3`–`c6`, `test_api_acceptance` |
| AGENT_MODE | `test_agent_mode` |
| API Auth | `test_api_auth`（10 项） |
| 文档 | `test_project_docs` |

`pytest.ini` 的 `norecursedirs` 排除 `legacy/`（含手动交互脚本）。

### 5.2 弱覆盖

- 真实 LLM 行为（无 golden eval）
- E2E 含 DeepSeek（手动/smoke）
- 并发/负载；本地 Docker CLI（CI 已验）

### 5.3 已解决的关键问题

| 问题 | 解决 |
|------|------|
| CI collect 需 API key | lazy OpenAI client |
| Docker 无 `.git` | 镜像内 git init |
| 审计仅截断 | P1 redaction |
| HTTP 无鉴权叙事 | P2 API Key |

---

## 6. 当前不足与技术债

### 6.1 真正影响水平的问题

| 问题 | 严重度 |
|------|--------|
| 无 unified diff | 高（改码叙事） |
| 无 LLM eval | 中高 |
| P0 无视觉 Demo | 中（展示） |
| 私有仓库 | 中（传播） |
| LLM 非确定性 | 中 |

### 6.2 锦上添花

README 英文、更多 redaction 规则、模型抽象、asciinema 外链。

### 6.3 不值得投入（当前阶段）

Web UI、Multi-Agent、RAG 合并、大量新工具、完整 OAuth/RBAC。

---

## 7. 与优秀 AI Agent 项目的差距

**当前阶段**：工程 MVP 上沿（强于课程 demo，弱于 SWE-agent/OpenHands 级 diff+eval+社区）。

| 维度 | RepoPilot 差距 |
|------|--------------|
| 改码粒度 | 整文件 vs patch |
| 评测 | 无 SWE-bench 类 eval |
| 社区/视觉 | 文档为主，缺 GIF/star |
| 求职 | 架构/CI 已达标；算法向需 diff 或 eval |

---

## 8. 后续路线评估（参考）

| 方向 | 工作量 | 推荐 |
|------|--------|------|
| P0 GIF/截图 | 0.5–1 天 | ★★★★★ |
| 公开 repo / Release 页 | 0.5–1 天 | ★★★★☆ |
| LLM eval 基线 | 2–3 天 | ★★★☆☆ |
| v0.4 unified diff | 5–10 天 | ★★★☆☆（独立大版本） |
| Web UI / Multi-Agent | 1–2 周+ | ★☆☆☆☆ |

---

## 9. 后续开发决策记录

> **决策日期**：2026-07-19 · **结论（v0.3.0 时点）**：v0.3.0 后 **暂停功能扩展**，优先包装与传播。  
> **后续（2026-07-20）**：v0.4.0 Unified Diff MVP 已在独立分支完成开发与验收；本节保留为历史决策记录。

### 9.1 为什么暂不做 Web UI

- **投入大**（1–2 周+）：前端栈、状态管理、SSE 消费、confirm 交互 UI
- **展示边际有限**：项目差异化在 **流程与安全网**，不在界面；CLI + curl + `/docs` 已够面试 demo
- **维护成本**：双端（CLI/API/UI）测试矩阵膨胀
- **替代方案**：P0 GIF 在 README 首屏达到 80% 视觉收益

### 9.2 为什么暂不做 Multi-Agent

- **叙事已完整（v0.3 时点）**：单 Agent ReAct + 12 工具已覆盖「读-改-审计」闭环；**v0.4** 增至 14 工具并增加 diff-first 路径
- **复杂度非线性上升**：任务分解、Agent 间状态、错误传播、审计 attribution 均需新设计
- **求职 ROI 低**：面试官更常问「你怎么保证写入安全」而非「几个 Agent 协作」
- **与 v0.3.0 策略一致**：明确不扩展 Agent 核心

### 9.3 为什么暂不做 RAG 合并

- 遗留 `legacy/agent.py`（Chroma + PDF）与 ReAct 主流程 **故意独立**
- RAG 合并需统一向量库、文档 ingest、与 tool 边界 — **偏离企业改码主线**
- 对「代码仓库 Agent」portfolio **故事线稀释**

### 9.4 为什么 unified diff 放到 v0.4.0 考虑（v0.3 时点 · 已实现）

- **工作量大**（5–10 天）：patch 解析/应用、冲突处理、测试矩阵、与现有整文件 write 共存
- **不应与 v0.3.x 包装任务捆绑**：v0.3.0 目标是展示与服务化，不是改码引擎升级
- **独立里程碑更清晰**：v0.4.0 = 「改码能力升级」；便于 CHANGELOG 与面试叙述
- **v0.4.0 交付（2026-07-20）**：**单文件 MVP**（`generate_unified_diff` + `apply_patch`）；保留 `write_repo_file`；不支持多文件 merge

### 9.5 为什么 P0 Demo 资产优先级最高

| 因素 | 说明 |
|------|------|
| **成本** | 0.5–1 天，零架构风险 |
| **收益** | GitHub 访客 30 秒内理解闭环；面试前无需 live 赌 LLM |
| **缺口明确** | 文档/测试/CI 已强，**视觉是唯一明显短板** |
| **不阻塞 release** | v0.3.0 已 tag；素材可后续 commit |
| **优于先写 v0.4** | 无 GIF 时继续堆功能，portfolio 首屏仍弱 |

---

## 10. 求职展示建议

### 10.1 GitHub README 首屏建议结构

```
1. 标题 + 一句话定位（企业代码仓库 Agent，非 ChatBot）
2. CI badge + 当前版本 **v0.4.0**（或 release 前 v0.4.0 candidate）
3. 【Demo 预览】GIF 或截图（P0 完成后置顶）
4. 核心闭环 mermaid（读→方案→确认→备份→写→审计→回滚）
5. 三大亮点（3–4 bullet）：Git 安全网 / 双重确认 / diff-first + write fallback / 双入口+SSE / **150 tests**+CI
6. 快速开始（3 行：clone → .env → react_agent 或 docker compose）
7. HTTP API 表（折叠或链接到下方详情）
8. 文档索引（architecture / workflow / demo / RETROSPECTIVE）
9. 版本线表格（v0.1→v0.3 一行摘要）
10. License
```

**首屏原则**：前 2 屏内出现 **GIF + mermaid + 一个 curl 示例**；细节下沉到 `docs/`。

### 10.2 简历项目描述建议

**项目名称**：RepoPilot — 企业代码仓库研发 Agent

**一句话**（简历摘要下）：
> 基于 ReAct 的企业仓库 Agent，实现读-方案-确认-备份-写入-审计-回滚全链路，CLI 与 FastAPI 双入口；v0.4 起支持单文件 unified diff 预览与应用，**150** 项测试与 CI/Docker 验证。

**技术栈**：Python · FastAPI · ReAct · DeepSeek · Git · SQLite · SSE · Docker · GitHub Actions

**职责/亮点**（4–6 bullet，择用）：

- 设计 ReAct Agent（v0.3：**12** 工具 → v0.4：**14** 工具），Pydantic 参数校验与 `full/readonly` 运行时模式过滤
- 实现双重确认改码流程与 Git 自动备份/回滚，JSONL 审计 + SQLite 任务 + Markdown 报告
- 开发 FastAPI 任务 API（异步执行、SSE、API 写确认），可选 API Key 与读取脱敏
- 搭建 GitHub Actions（pytest + Docker smoke），语义化版本 v0.1.0→v0.4.0

**量化**：87 pytest · 5 个 release tag · 8 个 HTTP 端点 · 12 ReAct 工具

**诚实边界**（面试主动提）：整文件写入非 diff；无 OAuth；LLM 非确定性。

### 10.3 面试重点技术问题清单

#### 架构与 Agent

1. ReAct 循环如何终止？步数限制与 `finish` 的区别？
2. CLI 与 API 如何共享同一套 Agent 逻辑？为何不用两套代码？
3. `parse_agent_response` 如何处理 LLM 输出不规范 JSON？
4. `AGENT_MODE` 在 prompt 层和 `run_tool` 层分别做什么？为何两层都要？

#### 安全与改码流程

5. 为什么改码要经过 `propose_code_changes` 而不是直接 `write_repo_file`？
6. 双重确认分别解决什么问题？API 模式如何实现写确认？
7. `path_guard` 与 `safe_write` 职责边界？
8. v0.3.0 读取脱敏如何设计？为何 env key 大小写敏感匹配？
9. Git backup 失败或用户无 commit 时行为？

#### 服务化与工程

10. `POST /tasks` 如何在后台跑 Agent？线程模型与 task 状态如何同步？
11. SSE 事件从 audit 到客户端的路径？completed 任务如何 replay？
12. API Key middleware 为何豁免 `/health`？空白 `API_KEY` 如何处理？
13. CI 为何能在无 `DEEPSEEK_API_KEY` 时跑 pytest？lazy client 解决什么？
14. Docker 镜像为何不复制宿主机 `.git`？baseline commit 作用？

#### 设计与权衡

15. v0.4 单文件 diff MVP 与整文件 write 如何共存？多文件 patch 为何不在 scope？
16. 为什么不做 Web UI / Multi-Agent？
17. 当前最大技术债是什么？若只有 1 天你会改什么？（期望：P0 GIF 或公开 repo）

---

## 11. 最终建议（v0.3.0 时点 · 历史）

> **v0.4.0 更新**：Unified Diff MVP 已完成；下一步为 merge + tag，而非继续堆叠 v0.4 范围外功能。

### 是否继续开发

**v0.3.0 后曾暂停大功能**；v0.4.0 diff MVP 已作为独立里程碑交付。

### 若继续，优先 3 件事

1. **P0 Demo 资产**（GIF + README 嵌入）
2. **（可选）公开仓库 / Release 页**
3. **（可选，另开 v0.4）unified diff** — 仅当岗位强调真实改码且可投入 1–2 周

### 不建议现在做

Web UI · Multi-Agent · RAG 合并 · v0.4 并行开发

---

## 附录：版本与测试速查

| Tag | 主题 | pytest |
|-----|------|--------|
| v0.1.0 | CLI MVP | 33 |
| v0.2.0 | HTTP API | 66 |
| v0.2.1 | AGENT_MODE | 66 |
| v0.2.2 | CI + Docker | 66 |
| v0.3.0 | 脱敏 + API Key | **87** |
| v0.4.0 | Unified Diff MVP（单文件） | **150** |

**P0 Demo 资产**：已完成（`demo-cli-read.gif` / `demo-cli-modify.gif` / `demo-cli-report.gif` 等，见 [DEMO_RECORDING.md](../DEMO_RECORDING.md)）。

**v0.4.0 状态（2026-07-20）**：release prep — merge master + tag 待执行。
