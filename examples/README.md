# Examples

本目录存放 **演示与测试用样本文件**，用于展示 RepoPilot 的仓库分析、读取、修改流程。

**不属于项目核心功能** — Agent、API、工具链不依赖此目录；可安全忽略或按需替换样本内容。

## demo_workspace/

| 文件 | 说明 |
|------|------|
| `demo_sample_a.txt` | 只读分析示例文本 |
| `demo_sample_b.txt` | 只读分析示例文本 |

完整复现步骤见 [docs/demo.md](../docs/demo.md)。Demo B 写入目标为项目根目录的 **`test.txt`**（与 [GITHUB_DEMO.md](../docs/GITHUB_DEMO.md) 一致）。

## Optional: RAG demo

RepoPilot 的 Repo RAG 默认关闭（`RAG_ENABLED=0`）。在 **repopilot 仓库根目录** 启用 hybrid search 的操作步骤见 [docs/RAG_DEMO.md](../docs/RAG_DEMO.md)（无需本目录样本文件）。
