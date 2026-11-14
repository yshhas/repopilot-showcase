"""Load system prompts from config/prompts.json with hardcoded fallback.

Before editing prompts, see config/prompts.json — no code changes needed.
"""

from __future__ import annotations

import json
import logging

from config.settings import PROJECT_ROOT

logger = logging.getLogger(__name__)

_PROMPTS_FILE = PROJECT_ROOT / "config" / "prompts.json"

# ---- Hardcoded fallback (kept in sync with prompts.json) ----

_FALLBACK_REACT_BASE = """\
你是企业内部软件研发管理 Agent，使用 ReAct 模式工作。

你的任务：
1. 读取和分析企业代码仓库资料（read_repo_file / list_repo_files / search_in_repo / analyze_repo_structure）；
2. 在用户要求修改代码时，先调用 propose_code_changes 生成结构化修改方案；
3. 用户确认执行后，优先使用 unified diff 流程（generate_unified_diff → git_create_backup → apply_patch → verify_change）；
   多文件修改时使用同一工具的 changes[] 参数；
   也可使用整文件覆盖流程（git_create_backup → write_repo_file → verify_change）作为备选；
4. 出错或用户要求撤销时，调用 git_rollback 回滚；
5. 读取仓库文件必须使用 read_repo_file，不要使用 file_reader；
6. 需要工具时返回 JSON；不需要工具时用自然语言回答。

重要约束：
- 不要跳过 propose_code_changes 直接写入；
- apply_patch / write_repo_file 执行前系统会弹出 CLI y/n 人工确认；
- 备份信息会写入 logs/last_backup.json，跨进程仍可回滚；
- 不要自行输出 raw unified diff 文本代替工具调用。
"""

# Other prompts omitted from fallback for brevity — they still live in prompts.json.
# If the JSON file is missing, the in-code definitions in llm.py serve as the
# ultimate fallback (they are loaded at module import time in llm.py).


def load_prompts() -> dict[str, str] | None:
    """Load prompts from config/prompts.json.

    Returns None when the file is missing / malformed (caller should use
    hardcoded definitions).
    """
    if not _PROMPTS_FILE.exists():
        return None

    try:
        data = json.loads(_PROMPTS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to parse prompts.json: %s", exc)
        return None

    if not isinstance(data, dict):
        return None

    return {
        "react_base": data.get("react_base", ""),
        "react_change": data.get("react_change", ""),
        "react_readonly": data.get("react_readonly", ""),
        "react_rules": data.get("react_rules", ""),
    }
