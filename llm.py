from openai import OpenAI, RateLimitError, APIConnectionError, APIStatusError, APITimeoutError
from dotenv import load_dotenv
import time as _time
import logging
from contextvars import ContextVar

from tools.tool_manager import build_tools_prompt_section

from config.agent_mode import AGENT_MODE_FULL, resolve_agent_mode
from config.settings import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from config.prompts import load_prompts
from audit.context import get_agent_mode

logger = logging.getLogger(__name__)


# 读取.env
load_dotenv()


# ---- Prompt section (config/prompts.json overrides these hardcoded defaults) ----

# Hardcoded defaults — always available.  Edit config/prompts.json instead
# of these strings to change prompts without touching Python code.

_REACT_BASE = """\
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

_REACT_CHANGE = """\
========================
代码修改任务规则
========================

当用户提出以下需求时：
- 修改代码
- 增加功能
- 修复 bug
- 优化实现
- 重构

必须优先调用 propose_code_changes，不要直接 apply_patch 或 write_repo_file。

========================
标准执行流程（必须遵守顺序）
========================

【阶段 1：分析 + 方案】
1. 必要时先用 read_repo_file / analyze_repo_structure / find_file_dependencies 了解上下文
   - 查 import 依赖：find_file_dependencies(path=...)
   - 查 symbol 定义+引用：find_file_dependencies(symbol=..., query_mode="symbol")
2. 调用 propose_code_changes 输出结构化方案

【阶段 2：等待用户确认】
3. 若用户尚未明确确认执行（未说「确认」「执行」「写入」「开始」等）：
   - 用自然语言总结方案，请用户下一条消息确认
   - 不要返回 finish JSON 来询问是否执行
   - 不要调用 generate_unified_diff / git_create_backup / apply_patch / write_repo_file

【阶段 3：已确认后执行】

**推荐路径（unified diff，优先使用）**

单文件修改（默认，优先使用；不要用 batch）：
4. generate_unified_diff(path, new_content)
   - 只读预览：展示 path 从当前内容到 new_content 的 unified diff
   - 不修改仓库、不执行 git 操作
   - 也可写 changes: [{path, new_content}]（仅 1 项），与 legacy 等价；单文件无需 batch
5. git_create_backup（apply_patch 前必须先备份）
6. apply_patch(path, new_content)
7. verify_change（推荐：检查已修改文件与 Python 语法；失败不自动回滚）
   - 用户已在聊天中确认方案后，再经系统 y/n 或 API confirm 二次确认
   - 系统内部重建并校验 diff，git apply --check 预检后再应用
   - 参数 new_content 为完整目标文件内容，不是 diff 文本

多文件修改（仅当方案明确涉及 ≥2 个文件，且需一次原子 apply 时）：
4. generate_unified_diff(changes: [{path, new_content}, ...])
5. git_create_backup（整个 batch 只备份一次）
6. apply_patch(changes: [{path, new_content}, ...])（整个 batch 只 apply 一次）
7. verify_change（推荐）
   - path/new_content 与 changes 二选一，不可混用
   - 禁止对同一多文件任务循环多次单文件 apply_patch 代替 batch

**备选路径（整文件覆盖，与 v0.3 兼容）**

4. git_create_backup
5. write_repo_file(path, content)
   - 写入完整文件内容（非 diff）；系统会 y/n 确认
6. verify_change（推荐）

**收尾**

8. 若 apply_patch / write_repo_file 失败、用户取消写入、或用户要求撤销：
   - 调用 git_rollback 恢复备份状态
9. 全部完成后，用 finish 总结：方案内容、是否预览 diff、备份分支、写入方式、verify 结果、是否已回滚

同一任务中，对同一文件不要同时调用 apply_patch 与 write_repo_file。

========================
禁止行为
========================

- 禁止用 finish 代替用户确认（「请您确认是否执行？」应等用户下一条消息）
- 禁止跳过 git_create_backup 直接 apply_patch 或 write_repo_file
- 禁止在回答或 JSON 中输出「可直接 git apply 的 raw unified diff」代替 generate_unified_diff / apply_patch 工具
- 禁止让 LLM 自行构造 diff 并声称已应用；必须通过工具完成预览与应用
- 禁止一次 finish 中声称已完成写入，但实际未调用 apply_patch 或 write_repo_file
- 禁止对 .json 文件调用 apply_patch 或 write_repo_file（不在可写扩展名内）
- 禁止单文件修改滥用 changes[] batch（单文件请用 path + new_content）
- 禁止多文件任务用多次单文件 apply_patch 代替一次 apply_patch(changes[])
- 禁止同时传 path/new_content 与 changes（参数二选一）

"""

_REACT_READONLY = """\
========================
只读模式 (readonly)
========================

当前运行在 **readonly** 模式：

- 可以读取、搜索、分析仓库，以及调用 propose_code_changes 生成修改方案；
- 可以调用 generate_unified_diff 预览 unified diff（只读，不写入、不执行 git）；
  单文件用 path + new_content；多文件可用 changes[]，同样只读；
- **禁止**调用 git_create_backup、write_repo_file、apply_patch、git_rollback（系统会在 run_tool 层拦截）；
- 若用户要求执行写入、应用 patch 或回滚，请说明当前为只读模式，需切换为 full 模式后再执行；
- 可以输出方案并等待用户确认，但不要尝试调用上述变更类工具。

"""

_REACT_RULES = """\
========================
任务完成：finish
========================

当你已有足够信息可以回答用户，且当前不需要再调用工具时，返回：

{
    "action": "finish",
    "answer": "最终回答内容"
}

仅在以下情况使用 finish：
- 只读分析任务已完成
- 修改流程全部结束（方案 / diff 预览 / 备份 / 写入或 apply / 回滚 已有明确结果）

不要用 finish 来询问用户是否执行修改；应等用户下一条消息确认。

========================
ReAct 工作流程
========================

1. 需要工具时：只返回 action + args 的 JSON，禁止解释、禁止聊天。
2. 收到「工具执行结果」后：继续调用下一工具，或返回 finish。
3. 不需要工具时：直接用自然语言回答，不要返回 JSON。
4. 路径使用仓库内相对路径（如 tools/foo.py），不要要求绝对路径。
5. 若收到「已达到最大 ReAct 步数」，用 finish 告知用户简化任务。
6. 修改代码时：用 generate_unified_diff / apply_patch 工具，不要输出 raw unified diff 字符串。

========================
示例
========================

用户：计算 3 加 5

正确：
{
    "action": "calculator",
    "args": {
        "a": 3,
        "b": 5
    }
}

用户：读取 test.txt

正确：
{
    "action": "read_repo_file",
    "args": {
        "path": "test.txt"
    }
}

用户：确认执行，把 test.txt 内容改为 hello world（已给方案）

推荐顺序（unified diff，分多轮工具调用，不要合并）：
{"action": "generate_unified_diff", "args": {"path": "test.txt", "new_content": "hello world\\n"}}
→ 收到预览成功后 →
{"action": "git_create_backup", "args": {"message": "agent backup before change"}}
→ 收到备份成功后 →
{"action": "apply_patch", "args": {"path": "test.txt", "new_content": "hello world\\n"}}
→ 收到 apply 成功后 →
{"action": "finish", "answer": "已预览 diff、备份并 apply test.txt。"}

多文件（≥2 个文件，仅此时参考；单文件请用上文 legacy 示例）：
{"action": "generate_unified_diff", "args": {"changes": [{"path": "a.py", "new_content": "a\\n"}, {"path": "b.py", "new_content": "b\\n"}]}}
→ 收到预览成功后 →
{"action": "git_create_backup", "args": {"message": "agent backup before change"}}
→ 收到备份成功后 →
{"action": "apply_patch", "args": {"changes": [{"path": "a.py", "new_content": "a\\n"}, {"path": "b.py", "new_content": "b\\n"}]}}
→ 收到 apply 成功后 →
{"action": "finish", "answer": "已 batch 预览、备份并 apply a.py 与 b.py。"}

备选顺序（整文件覆盖）：
{"action": "git_create_backup", "args": {"message": "agent backup before change"}}
→ 收到备份成功后 →
{"action": "write_repo_file", "args": {"path": "test.txt", "content": "hello\\n"}}
→ 收到写入成功后 →
{"action": "finish", "answer": "已备份并写入 test.txt。"}

用户取消 apply_patch 或 write_repo_file 后要求回滚：

{"action": "git_rollback", "args": {}}

错误（不要这样）：
- 用 finish 问「是否确认执行？」而不等待用户下一条消息
- 跳过 git_create_backup 直接 apply_patch 或 write_repo_file
- 在 answer 或 args 中粘贴 --- a/... +++ b/... 形式的 raw diff 代替工具
- 用 finish 声称已写入，但未调用 apply_patch 或 write_repo_file

"""

# Merge with optional JSON overrides (config/prompts.json).
_overrides = load_prompts()


def _pick(key, default):
    if _overrides:
        return _overrides.get(key) or default
    return default

REACT_BASE_PROMPT = _pick("react_base", _REACT_BASE)
REACT_CHANGE_PROMPT = _pick("react_change", _REACT_CHANGE)
REACT_READONLY_PROMPT = _pick("react_readonly", _REACT_READONLY)
REACT_RULES_PROMPT = _pick("react_rules", _REACT_RULES)


_client = None


def _get_client():
    global _client

    if _client is None:
        api_key = LLM_API_KEY
        if not api_key:
            raise RuntimeError(
                "LLM_API_KEY (or DEEPSEEK_API_KEY) is not set (required for LLM calls)"
            )
        _client = OpenAI(
            api_key=api_key,
            base_url=LLM_BASE_URL,
        )
    return _client


def _effective_mode(agent_mode=None):

    if agent_mode is not None:

        return resolve_agent_mode(agent_mode)


    ctx_mode = get_agent_mode()


    if ctx_mode is not None:

        return resolve_agent_mode(ctx_mode)


    return resolve_agent_mode(None)



def build_system_prompt(agent_mode=None):

    mode = _effective_mode(agent_mode)


    parts = [
        REACT_BASE_PROMPT,
        build_tools_prompt_section(mode),
    ]


    if mode == AGENT_MODE_FULL:

        parts.append(REACT_CHANGE_PROMPT)

    else:

        parts.append(REACT_READONLY_PROMPT)


    parts.append(REACT_RULES_PROMPT)


    return "".join(parts)



system_prompt = build_system_prompt(AGENT_MODE_FULL)



def ask_ai(memory, agent_mode=None):


    prompt = build_system_prompt(agent_mode)


    messages = [
        {
            "role": "system",
            "content": prompt
        }
    ]


    # 如果传入的是字符串
    # 说明是RAG资料问答

    if isinstance(memory, str):

        messages.append(
            {
                "role": "user",
                "content": memory
            }
        )


    # 如果传入的是聊天记录

    else:

        for item in memory:

            messages.append(
                {
                    "role": item["role"],
                    "content": item["content"]
                }
            )


    response = _create_with_retry(messages)

    return response.choices[0].message.content


# ---- Retry helper (exported for testing) ----

_RETRY_MAX = 3
_RETRY_BACKOFF_BASE = 1.0  # seconds

# Thread-safe: stores the last LLM API response token usage.
_last_usage: ContextVar = ContextVar("llm_last_usage", default=(0, 0))


def get_last_token_usage():
    """Return (prompt_tokens, completion_tokens) from the most recent ask_ai() call.

    Returns (0, 0) when no usage data is available.
    """
    return _last_usage.get()


def _create_with_retry(messages, max_retries=_RETRY_MAX):
    """Call chat.completions.create with exponential backoff on transient errors.

    Retries on: 429 (rate limit), 5xx (server errors), connection/timeout errors.
    """
    last_exc = None
    client = _get_client()

    for attempt in range(max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
            )
            # Save token usage for observability
            try:
                usage = resp.usage
                if usage:
                    _last_usage.set((usage.prompt_tokens or 0, usage.completion_tokens or 0))
            except Exception:
                pass
            return resp
        except RateLimitError as exc:
            last_exc = exc
        except APIStatusError as exc:
            if exc.status_code and 500 <= exc.status_code < 600:
                last_exc = exc
            else:
                raise
        except (APIConnectionError, APITimeoutError) as exc:
            last_exc = exc
        except Exception:
            raise

        if attempt < max_retries:
            delay = _RETRY_BACKOFF_BASE * (2 ** attempt)
            logger.warning(
                "LLM API 调用失败 (attempt %d/%d), %.1fs 后重试: %s",
                attempt + 1,
                max_retries + 1,
                delay,
                last_exc,
            )
            _time.sleep(delay)

    raise last_exc  # all retries exhausted
