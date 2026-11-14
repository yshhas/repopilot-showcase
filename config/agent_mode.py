from config.settings import AGENT_MODE as DEFAULT_AGENT_MODE_SETTING
from tools.result_schema import REJECT_CODE_TOOL_NOT_ALLOWED, tool_reject

AGENT_MODE_FULL = "full"

AGENT_MODE_READONLY = "readonly"

VALID_AGENT_MODES = {
    AGENT_MODE_FULL,
    AGENT_MODE_READONLY,
}

MUTATION_TOOLS = frozenset({
    "git_create_backup",
    "write_repo_file",
    "git_rollback",
    "apply_patch",
})

# Full-mode only (not mutation writes, but meaningless / blocked in readonly).
VERIFY_TOOLS = frozenset({
    "verify_change",
})

READONLY_BLOCKED_TOOLS = MUTATION_TOOLS | VERIFY_TOOLS

FULL_TOOL_ORDER = [
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

READONLY_TOOL_ORDER = [
    name
    for name in FULL_TOOL_ORDER
    if name not in READONLY_BLOCKED_TOOLS
]


def parse_agent_mode(value):

    if value is None:

        return AGENT_MODE_FULL


    mode = str(value).strip().lower()


    if mode not in VALID_AGENT_MODES:

        raise ValueError(
            "invalid agent mode: "
            + repr(value)
            + " (expected readonly or full)"
        )


    return mode



def resolve_agent_mode(request_mode=None):

    if request_mode is not None:

        return parse_agent_mode(request_mode)


    return parse_agent_mode(DEFAULT_AGENT_MODE_SETTING)



def get_tool_order_for_mode(mode):

    parsed = parse_agent_mode(mode)


    if parsed == AGENT_MODE_READONLY:

        return READONLY_TOOL_ORDER


    return FULL_TOOL_ORDER



def is_tool_allowed(mode, tool_name):

    parsed = parse_agent_mode(mode)


    if parsed == AGENT_MODE_FULL:

        return True


    return tool_name not in READONLY_BLOCKED_TOOLS



def tool_blocked_message(tool_name, mode):

    return (
        "工具 "
        + tool_name
        + " 在 "
        + parse_agent_mode(mode)
        + " 模式下不可用"
    )


def tool_blocked_reject(tool_name, mode):
    message = tool_blocked_message(tool_name, mode)
    return tool_reject(
        REJECT_CODE_TOOL_NOT_ALLOWED,
        message,
        details={
            "tool": tool_name,
            "agent_mode": parse_agent_mode(mode),
        },
    )
