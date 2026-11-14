# Demo 资产目录

本目录存放 GitHub 展示用截图与动图。录制步骤见 **[DEMO_RECORDING.md](../DEMO_RECORDING.md)**。

> README 当前仅嵌入 `demo-audit-report.jpg`（真实终端任务审计输出）。新增图片前请先录制真实运行画面并提交到本目录，避免坏链。

## 展示图片

| 文件 | 用途 | 状态 |
|------|------|------|
| `demo-audit-report.jpg` | 真实任务审计报告终端输出 | ✅ 已包含 |

## 关于其他图片

早期设计稿风格的界面示意图（PNG）与三个 GIF 录屏未包含在公开仓库中：前者并非真实运行截图，后者体积较大。录制真实画面请参考 [DEMO_RECORDING.md](../DEMO_RECORDING.md)。

## 体积建议

- PNG：宽度 ≤ 1280px，适当压缩
- GIF（本地演示用）：宽度 960–1280px，10–12 fps；单文件目标 **< 8 MB**

提交图片后，可在 [README.md](../../README.md) 的 Demo 预览区重新加入 Markdown 图片引用；[`test_project_docs.py`](../../test_project_docs.py) 会校验：**凡 README 引用的 `docs/assets/*` 图片文件必须存在**。
