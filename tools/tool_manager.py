from tools.pdf_reader import read_pdf
from tools.vector_store import search
from tools.summarizer import summarize
from tools.calculator import calculate
from tools.file_reader import read_file
from tools.repo_reader import list_repo_files, read_repo_file, search_in_repo
from tools.repo_analyzer import analyze_repo_structure, find_file_dependencies
from tools.change_proposal import propose_code_changes
from tools.git_tools import git_create_backup, git_rollback, git_status
from tools.safe_write import write_repo_file
from tools.diff_engine import generate_unified_diff
from tools.patch_apply import apply_patch
from tools.verify_change import verify_change

from pydantic import ValidationError

import logging
import time

from schemas import (
    AnalyzeRepoStructureArgs,
    ApplyPatchArgs,
    CalculatorArgs,
    FileReaderArgs,
    FindFileDependenciesArgs,
    GenerateUnifiedDiffArgs,
    GitCreateBackupArgs,
    GitRollbackArgs,
    GitStatusArgs,
    ListRepoFilesArgs,
    ProposeCodeChangesArgs,
    ReadRepoFileArgs,
    SearchInRepoArgs,
    SummarizerArgs,
    VerifyChangeArgs,
    WriteRepoFileArgs,
)
from audit.audit_log import log_tool_call, write_audit_event
from audit.context import (
    get_agent_mode,
    get_confirm_callback,
    get_task_id,
    is_tool_confirm_skipped,
)
from config.agent_mode import (
    get_tool_order_for_mode,
    is_tool_allowed,
    resolve_agent_mode,
    tool_blocked_reject,
)
from config.settings import CONFIRM_REQUIRED_TOOLS
from security.tool_confirm import request_tool_confirmation
from tools.result_schema import (
    REJECT_CODE_CONFIRM_REJECTED,
    REJECT_CODE_TOOL_NOT_FOUND,
    REJECT_CODE_VALIDATION_ERROR,
    UNKNOWN_TOOL_MESSAGE,
    ToolResult,
    tool_reject,
)
from tools.outcome_schema import finalize_tool_outcome, normalize_tool_outcome

logger = logging.getLogger(__name__)


REACT_TOOL_ORDER = [
    "summarizer",
    "calculator",
    "list_repo_files",
    "read_repo_file",
    "search_in_repo",
    "analyze_repo_structure",
    "find_file_dependencies",
    "propose_code_changes",
    "git_status",
    "generate_unified_diff",
    "git_create_backup",
    "write_repo_file",
    "apply_patch",
    "verify_change",
    "git_rollback",
]


TOOLS = {


"pdf_reader":
{
    "description":
    "读取PDF文件",

    "function":
    read_pdf,

    "react":
    False,

    "parameters":
    {
        "path":
        {
            "type":
            "string",

            "description":
            "PDF文件路径",

            "example":
            "\"文件路径\""
        }
    }
},



"search":
{
    "description":
    "从知识库搜索相关内容",

    "function":
    search,

    "react":
    False,

    "parameters":
    {
        "query":
        {
            "type":
            "string",

            "description":
            "搜索关键词",

            "example":
            "\"搜索词\""
        },

        "n":
        {
            "type":
            "number",

            "description":
            "返回结果数量",

            "example":
            "3"
        }
    }
},



"summarizer":
{
    "description":
    "总结用户提供的文本",

    "function":
    summarize,

    "react":
    True,

    "args_model":
    SummarizerArgs,

    "parameters":
    {
        "text":
        {
            "type":
            "string",

            "description":
            "需要总结的文本",

            "example":
            "\"需要总结的文本\""
        }
    }
},



"calculator":
{
    "description":
    "计算两个数字相加",

    "function":
    calculate,

    "react":
    True,

    "args_model":
    CalculatorArgs,

    "parameters":
    {
        "a":
        {
            "type":
            "number",

            "description":
            "第一个数字",

            "example":
            "数字"
        },

        "b":
        {
            "type":
            "number",

            "description":
            "第二个数字",

            "example":
            "数字"
        }
    }
},



"file_reader":
{
    "description":
    "读取文本文件（.txt）",

    "usage":
    "读取文件、查看文件内容、打开 txt 文件",

    "notes":
    "用户说「读取 test.txt」时，默认文件在当前项目目录，返回：",

    "notes_example":
    {
        "path":
        "\"test.txt\""
    },

    "function":
    read_file,

    "react":
    False,

    "args_model":
    FileReaderArgs,

    "parameters":
    {
        "path":
        {
            "type":
            "string",

            "description":
            "文件路径",

            "example":
            "\"文件路径\""
        }
    }
},



"list_repo_files":
{
    "description":
    "列出企业代码仓库中的文件",

    "usage":
    "查看项目结构、列出某目录下的代码文件、按扩展名筛选",

    "function":
    list_repo_files,

    "react":
    True,

    "args_model":
    ListRepoFilesArgs,

    "parameters":
    {
        "path":
        {
            "type":
            "string",

            "description":
            "仓库内相对路径，默认为根目录",

            "example":
            "\"tools\""
        },

        "extensions":
        {
            "type":
            "string",

            "description":
            "扩展名过滤，逗号分隔，如 .py,.md",

            "example":
            "\".py,.md\""
        },

        "max_results":
        {
            "type":
            "number",

            "description":
            "最多返回多少个文件",

            "example":
            "100"
        }
    }
},



"read_repo_file":
{
    "description":
    "读取企业代码仓库内的指定文件",

    "usage":
    "查看源码、配置文件、文档内容；path 必须是仓库内相对路径",

    "function":
    read_repo_file,

    "react":
    True,

    "args_model":
    ReadRepoFileArgs,

    "parameters":
    {
        "path":
        {
            "type":
            "string",

            "description":
            "仓库内相对路径",

            "example":
            "\"react_agent.py\""
        },

        "max_chars":
        {
            "type":
            "number",

            "description":
            "最多读取多少字符",

            "example":
            "20000"
        }
    }
},



"search_in_repo":
{
    "description":
    "在企业代码仓库中搜索关键字",

    "usage":
    "查找函数名、类名、配置项、接口路径等",

    "function":
    search_in_repo,

    "react":
    True,

    "args_model":
    SearchInRepoArgs,

    "parameters":
    {
        "keyword":
        {
            "type":
            "string",

            "description":
            "搜索关键词",

            "example":
            "\"run_tool\""
        },

        "path":
        {
            "type":
            "string",

            "description":
            "限定搜索的仓库内目录，默认全仓库",

            "example":
            "\"tools\""
        },

        "extensions":
        {
            "type":
            "string",

            "description":
            "扩展名过滤，逗号分隔",

            "example":
            "\".py\""
        },

        "max_results":
        {
            "type":
            "number",

            "description":
            "最多返回多少条匹配",

            "example":
            "20"
        }
    }
},



"analyze_repo_structure":
{
    "description":
    "分析企业代码仓库的项目结构",

    "usage":
    "了解目录树、关键文件、模块分布和架构层次",

    "function":
    analyze_repo_structure,

    "react":
    True,

    "args_model":
    AnalyzeRepoStructureArgs,

    "parameters":
    {
        "path":
        {
            "type":
            "string",

            "description":
            "仓库内相对路径，默认为根目录",

            "example":
            "\".\""
        },

        "max_depth":
        {
            "type":
            "number",

            "description":
            "目录树最大深度",

            "example":
            "3"
        }
    }
},



"find_file_dependencies":
{
    "description":
    "分析 Python 文件 import 依赖，或按 symbol 查询定义与引用（需 index）",

    "usage":
    "dependencies: path 查 import/dependents；symbol: symbol 查定义+引用（query_mode=symbol 或 auto+symbol）",

    "function":
    find_file_dependencies,

    "react":
    True,

    "args_model":
    FindFileDependenciesArgs,

    "parameters":
    {
        "path":
        {
            "type":
            "string",

            "description":
            "仓库内 Python 文件相对路径（dependencies 模式必填）",

            "example":
            "\"react_agent.py\""
        },

        "symbol":
        {
            "type":
            "string",

            "description":
            "符号名（symbol 模式必填，如类名/函数名）",

            "example":
            "\"FileChange\""
        },

        "query_mode":
        {
            "type":
            "string",

            "description":
            "dependencies | symbol | auto（默认 auto：有 symbol 走 symbol，否则 path 走 dependencies）",

            "example":
            "\"auto\""
        },

        "max_results":
        {
            "type":
            "number",

            "description":
            "最多返回多少条依赖/引用",

            "example":
            "100"
        }
    }
},



"propose_code_changes":
{
    "description":
    "基于项目资料生成结构化代码修改方案",

    "usage":
    "用户要求改代码、加功能、修复问题时，先调用此工具输出方案，不要直接改文件",

    "function":
    propose_code_changes,

    "react":
    True,

    "args_model":
    ProposeCodeChangesArgs,

    "parameters":
    {
        "task":
        {
            "type":
            "string",

            "description":
            "修改任务描述，说明目标与期望",

            "example":
            "\"给 run_tool 增加更详细的错误日志\""
        },

        "target_files":
        {
            "type":
            "string",

            "description":
            "可选，逗号分隔的仓库内文件路径，用于补充上下文",

            "example":
            "\"tools/tool_manager.py,react_agent.py\""
        },

        "affected_files":
        {
            "type":
            "string",

            "description":
            "可选，逗号分隔的相关文件路径，用于 context ranking（优先级高于 target_files）",

            "example":
            "\"schemas.py,tools/patch_apply.py\""
        },

        "max_chars":
        {
            "type":
            "number",

            "description":
            "读取每个上下文文件的最大字符数",

            "example":
            "20000"
        }
    }
},



"git_status":
{
    "description":
    "查看当前 Git 仓库状态",

    "usage":
    "修改代码前检查分支、commit 和工作区是否有未提交变更",

    "function":
    git_status,

    "react":
    True,

    "args_model":
    GitStatusArgs,

    "parameters":
    {}
},



"generate_unified_diff":
{
    "description":
    "生成 unified diff 预览（只读，不修改仓库；单文件或 batch）",

    "usage":
    "用户确认修改方案后、Git 备份与 apply 前预览差异；"
    "单文件（默认）用 path + new_content；"
    "多文件（≥2）用 changes: [{path, new_content}, ...]；"
    "path/new_content 与 changes 二选一，不可混用；"
    "不产生任何文件写入或 Git 操作",

    "function":
    generate_unified_diff,

    "react":
    True,

    "args_model":
    GenerateUnifiedDiffArgs,

    "parameters":
    {
        "path":
        {
            "type":
            "string",

            "description":
            "单文件 legacy：仓库内相对路径（与 new_content 成对；与 changes 二选一）",

            "example":
            "\"tools/example.py\""
        },

        "new_content":
        {
            "type":
            "string",

            "description":
            "单文件 legacy：目标文件完整 UTF-8 文本（与 path 成对；与 changes 二选一）",

            "example":
            "\"print(\\\"hello\\\")\\n\""
        },

        "changes":
        {
            "type":
            "array",

            "description":
            "多文件 batch：[{path, new_content}, ...]，1..PATCH_MAX_FILES，path 唯一；"
            "单文件也可用仅 1 项（与 legacy 等价）；与 path/new_content 二选一",

            "example":
            "[{\"path\": \"a.py\", \"new_content\": \"...\\n\"}, {\"path\": \"b.py\", \"new_content\": \"...\\n\"}]"
        }
    }
},



"git_create_backup":
{
    "description":
    "在修改代码前创建 Git 备份分支并 commit 当前状态",

    "usage":
    "执行文件修改前必须先备份；会创建 agent-backup/时间戳 分支",

    "function":
    git_create_backup,

    "react":
    True,

    "args_model":
    GitCreateBackupArgs,

    "parameters":
    {
        "message":
        {
            "type":
            "string",

            "description":
            "备份 commit 的说明",

            "example":
            "\"agent backup before change\""
        }
    }
},



"write_repo_file":
{
    "description":
    "向企业代码仓库内的指定文件写入内容（整文件覆盖）",

    "usage":
    "用户确认修改方案且已备份后执行；path 为仓库内相对路径，content 为完整新内容",

    "function":
    write_repo_file,

    "react":
    True,

    "args_model":
    WriteRepoFileArgs,

    "parameters":
    {
        "path":
        {
            "type":
            "string",

            "description":
            "仓库内相对路径",

            "example":
            "\"tools/example.py\""
        },

        "content":
        {
            "type":
            "string",

            "description":
            "写入文件的完整 UTF-8 文本内容",

            "example":
            "\"print(\\\"hello\\\")\\n\""
        }
    }
},



"apply_patch":
{
    "description":
    "通过 unified diff 应用修改（git apply；单文件或 batch）",

    "usage":
    "用户确认 diff 预览且已 git_create_backup 后执行；"
    "单文件（默认）用 path + new_content；"
    "多文件（≥2）用 changes: [{path, new_content}, ...]（一次 backup + 一次 apply）；"
    "path/new_content 与 changes 二选一；"
    "系统会校验 diff、git apply --check 预检，并在 y/n 或 API confirm 通过后再应用",

    "function":
    apply_patch,

    "react":
    True,

    "args_model":
    ApplyPatchArgs,

    "parameters":
    {
        "path":
        {
            "type":
            "string",

            "description":
            "单文件 legacy：仓库内相对路径（与 new_content 成对；与 changes 二选一）",

            "example":
            "\"tools/example.py\""
        },

        "new_content":
        {
            "type":
            "string",

            "description":
            "单文件 legacy：目标文件完整 UTF-8 文本（与 path 成对；与 changes 二选一）",

            "example":
            "\"print(\\\"hello\\\")\\n\""
        },

        "changes":
        {
            "type":
            "array",

            "description":
            "多文件 batch：[{path, new_content}, ...]，1..PATCH_MAX_FILES，path 唯一；"
            "与 path/new_content 二选一",

            "example":
            "[{\"path\": \"a.py\", \"new_content\": \"...\\n\"}, {\"path\": \"b.py\", \"new_content\": \"...\\n\"}]"
        }
    }
},



"verify_change":
{
    "description":
    "改码后验证（检查已修改文件是否存在、Python 语法是否合法）",

    "usage":
    "apply_patch 或 write_repo_file 成功后调用；"
    "默认检查 patched_files + syntax；"
    "paths 为空时使用本次任务已 apply 的路径；"
    "验证失败不会自动回滚，可继续 finish / git_rollback / 重新改码",

    "function":
    verify_change,

    "react":
    True,

    "args_model":
    VerifyChangeArgs,

    "parameters":
    {
        "checks":
        {
            "type":
            "string",

            "description":
            "逗号分隔检查项：patched_files,syntax（默认两者）",

            "example":
            "\"patched_files,syntax\""
        },

        "paths":
        {
            "type":
            "string",

            "description":
            "可选：逗号分隔相对路径；默认使用 TMS 已 apply 路径",

            "example":
            "\"tools/example.py\""
        }
    }
},



"git_rollback":
{
    "description":
    "将当前分支回滚到最近一次 git_create_backup 记录的备份状态",

    "usage":
    "修改出错、用户要求撤销、或 write_repo_file 失败后恢复仓库时使用",

    "function":
    git_rollback,

    "react":
    True,

    "args_model":
    GitRollbackArgs,

    "parameters":
    {}
}



}



def get_react_tools(agent_mode=None):


    if agent_mode is None:

        ctx_mode = get_agent_mode()


        if ctx_mode is not None:

            agent_mode = ctx_mode

        else:

            agent_mode = resolve_agent_mode(None)


    allowed = set(get_tool_order_for_mode(agent_mode))

    react_tools = {}


    for name in get_tool_order_for_mode(agent_mode):


        tool = TOOLS.get(name)


        if tool and tool.get("react") and name in allowed:

            react_tools[name] = tool


    return react_tools



def format_tool_json_example(name, parameters):


    args_lines = []


    for param_name in parameters:

        param = parameters[param_name]

        args_lines.append(
            "        \""
            + param_name
            + "\": "
            + param["example"]
        )


    args_body = ",\n".join(args_lines)


    return (
        "{\n"
        "    \"action\": \""
        + name
        + "\",\n"
        "    \"args\": {\n"
        + args_body
        + "\n"
        "    }\n"
        "}"
    )



def build_tools_prompt_section(agent_mode=None):


    lines = [

        "",

        "你拥有以下工具（action 名称必须与下表完全一致）：",

        ""

    ]


    react_tools = get_react_tools(agent_mode)

    tool_order = get_tool_order_for_mode(
        agent_mode
        if agent_mode is not None
        else (get_agent_mode() or resolve_agent_mode(None))
    )


    tool_index = 0


    for name in tool_order:


        if name not in react_tools:

            continue


        tool = react_tools[name]


        tool_index += 1


        lines.append(
            "========================"
        )

        lines.append(
            "工具"
            + str(tool_index)
            + "："
            + name
        )

        lines.append(
            "========================"
        )

        lines.append("")

        lines.append(
            "作用："
            + tool["description"]
        )

        lines.append("")


        if tool.get("usage"):

            lines.append(
                "适用场景："
                + tool["usage"]
            )

            lines.append("")


        if tool_index == 1:

            lines.append(
                "调用格式（只返回 JSON，不要其他文字）："
            )

        else:

            lines.append(
                "调用格式："
            )

        lines.append("")

        lines.append(
            format_tool_json_example(
                name,
                tool["parameters"]
            )
        )

        lines.append("")


        if tool.get("notes"):

            lines.append(
                "说明："
                + tool["notes"]
            )

            lines.append("")


            if tool.get("notes_example"):

                notes_parameters = {}


                for param_name in tool["notes_example"]:

                    notes_parameters[param_name] = {

                        "example":
                        tool["notes_example"][param_name]

                    }


                lines.append(
                    format_tool_json_example(
                        name,
                        notes_parameters
                    )
                )

                lines.append("")


    return "\n".join(lines)


EXECUTION_STATE_DEDUP_TOOLS = frozenset({
    "git_create_backup",
    "apply_patch",
    "write_repo_file",
})


def _execution_state_dedup_skip(name, args):
    if name not in EXECUTION_STATE_DEDUP_TOOLS:
        return None

    try:
        from context.tms.guards import (
            is_dedup_guard_enabled,
            should_skip_tool_tms,
        )

        if not is_dedup_guard_enabled():
            return None

        skip_message = should_skip_tool_tms(name, args)
        if skip_message:
            write_audit_event({
                "event": "execution_state_dedup",
                "tool": name,
                "status": "skipped",
                "reason": "duplicate_mutation",
                "guard_source": "tms",
            })

        return skip_message
    except Exception as e:
        logger.warning("_execution_state_dedup 失败: %s", e, exc_info=True)
        return None


def _mutation_fsm_check(name, args, agent_mode):
    try:
        from context.tms.guards import (
            build_mutation_guard_blocked_audit,
            check_mutation_allowed,
            is_mutation_guard_enabled,
        )

        reject = check_mutation_allowed(name, args, agent_mode=agent_mode)
        if reject and is_mutation_guard_enabled():
            write_audit_event(build_mutation_guard_blocked_audit(name, reject))
        return reject
    except Exception as e:
        logger.warning("_mutation_fsm_check 失败: %s", e, exc_info=True)
        return None


def _mutation_fsm_advance(name, args, result):
    return


def _finalize_run_tool_result(name, args, result: ToolResult) -> ToolResult:
    outcome = normalize_tool_outcome(result, tool=name, args=args)
    return finalize_tool_outcome(outcome)


def _validation_error_reject(tool_name, field, msg):
    if field:
        message = "参数错误: " + str(field) + " - " + msg
    else:
        message = "参数错误: " + msg

    return tool_reject(
        REJECT_CODE_VALIDATION_ERROR,
        message,
        details={
            "tool": tool_name,
            "field": str(field) if field else None,
            "validation_msg": msg,
        },
    )


def _confirm_rejected(tool_name):
    return tool_reject(
        REJECT_CODE_CONFIRM_REJECTED,
        "用户已取消执行工具: " + tool_name,
        details={"tool": tool_name},
    )


def _tool_not_found_reject(tool_name):
    return tool_reject(
        REJECT_CODE_TOOL_NOT_FOUND,
        UNKNOWN_TOOL_MESSAGE,
        details={"tool": tool_name},
    )


def _invoke_registered_tool(name, args, tool):
    skip_message = _execution_state_dedup_skip(name, args)
    if skip_message:
        return skip_message

    if (
        name in CONFIRM_REQUIRED_TOOLS
        and not is_tool_confirm_skipped()
        and not request_tool_confirmation(
            name,
            args,
            confirm_callback=get_confirm_callback(),
        )
    ):
        return _confirm_rejected(name)

    return tool["function"](**args)


def run_tool(name, args):


    start = time.perf_counter()

    result: ToolResult


    if name not in TOOLS:

        result = _tool_not_found_reject(name)


    else:

        mode = get_agent_mode()


        if mode is None:

            mode = resolve_agent_mode(None)


        if not is_tool_allowed(mode, name):

            result = tool_blocked_reject(name, mode)


        else:

            tool = TOOLS[name]


            args_model = tool.get("args_model")


            if args_model:

                try:

                    validated = args_model.model_validate(args)

                    args = validated.model_dump()


                except ValidationError as e:


                    errors = e.errors()


                    if errors:

                        first = errors[0]

                        loc = first.get("loc", ())
                        field = loc[0] if loc else ""

                        msg = first.get("msg", str(e))

                        result = _validation_error_reject(name, field, msg)

                    else:

                        result = _validation_error_reject(name, "", str(e))

                else:

                    fsm_reject = _mutation_fsm_check(name, args, mode)

                    if fsm_reject:

                        result = fsm_reject

                    else:

                        result = _invoke_registered_tool(name, args, tool)


            else:

                fsm_reject = _mutation_fsm_check(name, args, mode)

                if fsm_reject:

                    result = fsm_reject

                else:

                    result = _invoke_registered_tool(name, args, tool)


    result = _finalize_run_tool_result(name, args, result)

    duration_ms = (time.perf_counter() - start) * 1000


    log_tool_call(
        name,
        args,
        result,
        duration_ms,
        get_task_id(),
    )


    return result
