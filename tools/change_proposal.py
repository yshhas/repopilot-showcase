
import config.settings as settings
from audit.audit_log import write_audit_event
from context.budget_state import record_context_read
from index.ranking import (
    add_candidate,
    apply_context_budget,
    candidates_from_retrieval_hits,
    format_selection_summary,
    rank_file_candidates,
)
from schemas import ChangeProposalList, extract_json_dict
from tools.repo_analyzer import _find_file_dependencies_legacy, analyze_repo_structure
from tools.repo_reader import read_repo_file
from tools.outcome_schema import SUCCESS_CODE_PROPOSAL_GENERATED, tool_success
from context.execution_state import compute_proposal_digest
from context.tms.types import MilestoneToken



def _format_proposal(proposal: ChangeProposalList):

    lines = [

        "===== 修改方案 =====",

        "",

        "摘要: "
        + proposal.summary,

        "",

        "共 "
        + str(len(proposal.proposals))
        + " 条建议：",

        "",

    ]


    for index, item in enumerate(proposal.proposals, start=1):

        lines.extend([

            "【建议 "
            + str(index)
            + "】",

            "文件: "
            + item.file,

            "类型: "
            + item.change_type,

            "风险: "
            + item.risk,

            "说明: "
            + item.description,

            "预览: "
            + item.preview,

            "",

        ])


    lines.append("说明: 以上为修改方案，尚未执行任何文件改动。")


    return "\n".join(lines)



def _load_context_legacy(
    target_files,
    max_chars,
):

    sections = []


    if target_files.strip():

        paths = [
            path.strip()
            for path in target_files.split(",")
            if path.strip()
        ]


        per_file_limit = max(
            1000,
            max_chars // max(1, len(paths)),
        )


        for path in paths:

            content = read_repo_file(
                path,
                max_chars=per_file_limit,
            )

            sections.append(
                "===== 文件: "
                + path
                + " =====\n"
                + content
            )


    else:

        sections.append(
            analyze_repo_structure(
                path=".",
                max_depth=2,
            )
        )


    return "\n\n".join(sections)



def _estimate_file_chars(path: str) -> int:
    from security.path_guard import is_allowed_extension, is_blocked_file, resolve_repo_path

    try:
        file_path = resolve_repo_path(path)
        if not file_path.is_file() or is_blocked_file(file_path):
            return 0
        if not is_allowed_extension(file_path):
            return 0
        return len(file_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return 4000



def _expand_dependency_candidates(anchor_path: str, max_results: int = 20):
    report = _find_file_dependencies_legacy(anchor_path, max_results=max_results)
    imports: list[str] = []
    dependents: list[str] = []
    section = None

    for line in report.splitlines():
        if line == "===== 本文件 import =====":
            section = "imports"
            continue
        if line == "===== 可能依赖本文件的模块 =====":
            section = "dependents"
            continue
        if line.startswith("说明:"):
            break
        if section == "imports" and line and not line.startswith("("):
            imports.append(line.strip())
        if section == "dependents" and line and not line.startswith("("):
            dependents.append(line.strip())

    return imports, dependents



def _parse_path_list(raw: str) -> list[str]:
    return [path.strip() for path in str(raw or "").split(",") if path.strip()]



def _load_context_with_budget(
    target_files,
    max_chars,
    affected_files=None,
    task_description=None,
):
    explicit_paths = _parse_path_list(target_files)
    affected = list(affected_files or [])

    bucket: dict = {}

    for path in affected:
        add_candidate(bucket, path, 100.0, "affected_files", "explicit affected_files")

    for path in explicit_paths:
        add_candidate(bucket, path, 95.0, "target_files", "explicit target_files")

    rank_source_parts = []
    if affected:
        rank_source_parts.append("affected_files")
    if explicit_paths:
        rank_source_parts.append("target_files")

    if task_description and settings.RAG_ENABLED and settings.RAG_CONTEXT_EXPAND:
        from rag.context_expand import expand_semantic_candidates, task_query_hash

        semantic_hits = expand_semantic_candidates(task_description)
        if semantic_hits:
            for candidate in candidates_from_retrieval_hits(semantic_hits):
                add_candidate(
                    bucket,
                    candidate.path,
                    candidate.score,
                    "semantic",
                    candidate.reason,
                )
            rank_source_parts.append("semantic")

            write_audit_event({
                "event": "rag_context_expand",
                "task_hash": task_query_hash(task_description),
                "candidate_count": len(semantic_hits),
                "candidate_paths": ", ".join(
                    sorted({hit.path for hit in semantic_hits})[:20]
                ),
            })

    anchor = explicit_paths[0] if explicit_paths else (affected[0] if affected else "")
    if anchor and anchor.endswith(".py"):
        imports, dependents = _expand_dependency_candidates(anchor)
        for item in imports:
            add_candidate(bucket, item.replace(".", "/") + ".py", 55.0, "import_neighbor", "import of " + anchor)
        for item in dependents:
            add_candidate(bucket, item, 60.0, "dependent_neighbor", "dependent of " + anchor)
        rank_source_parts.append("dependency_expand")

    if not bucket:
        return _load_context_legacy(target_files, max_chars)

    candidates = list(bucket.values())
    ranked = rank_file_candidates(candidates)

    estimates = {item.path: _estimate_file_chars(item.path) for item in ranked}
    budget_result = apply_context_budget(
        ranked,
        budget_chars=min(max_chars, settings.CONTEXT_BUDGET_CHARS),
        rank_source="+".join(rank_source_parts) or "target_files",
        file_char_estimates=estimates,
    )

    write_audit_event({
        "event": "context_budget_applied",
        "candidates_count": budget_result.candidates_count,
        "selected_count": budget_result.selected_count,
        "truncated_count": budget_result.truncated_count,
        "truncation_reason": budget_result.truncation_reason,
        "budget_chars": budget_result.budget_chars,
        "chars_used": budget_result.chars_used,
        "truncated_paths": ", ".join(item.path for item in budget_result.truncated[:20]),
        "selected_paths": ", ".join(item.path for item in budget_result.selected[:20]),
        "rank_source": budget_result.rank_source,
    })

    sections = []
    chars_used = 0

    for candidate in budget_result.selected:
        remaining = budget_result.budget_chars - chars_used
        if remaining <= 0:
            break

        per_file_limit = max(1000, min(remaining, max_chars // max(1, budget_result.selected_count)))
        content = read_repo_file(candidate.path, max_chars=per_file_limit)
        sections.append("===== 文件: " + candidate.path + " =====\n" + content)
        record_context_read(candidate.path, min(per_file_limit, remaining))
        chars_used += min(per_file_limit, remaining)

    sections.append(format_selection_summary(budget_result))

    return "\n\n".join(sections)



def _load_context(
    target_files,
    max_chars,
    affected_files=None,
    task_description=None,
):

    if not settings.CONTEXT_BUDGET_ENABLED:
        return _load_context_legacy(target_files, max_chars)

    return _load_context_with_budget(
        target_files,
        max_chars,
        affected_files=affected_files,
        task_description=task_description,
    )



def propose_code_changes(
    task,
    target_files="",
    max_chars=20000,
    affected_files="",
):

    try:

        if not task or not task.strip():

            return "任务描述不能为空"


        from llm import ask_ai

        affected_list = _parse_path_list(affected_files)

        context = _load_context(
            target_files,
            max_chars,
            affected_files=affected_list or None,
            task_description=task.strip(),
        )


        prompt = f"""
你是企业内部软件研发管理助手。
请基于项目资料，针对任务给出结构化修改方案。

任务：
{task.strip()}

项目资料：
{context}

要求：
1. 只输出 JSON，不要输出其他解释文字。
2. 此阶段只提方案，不执行任何文件修改。
3. 不要编造不存在的文件。
4. JSON 格式必须为：
{{
    "summary": "总体修改说明",
    "affected_files": ["可选，相关文件路径列表，用于上下文排序"],
    "proposals": [
        {{
            "file": "仓库内相对路径",
            "change_type": "modify",
            "description": "为什么要改，改什么",
            "risk": "low",
            "preview": "建议改动概述或关键代码片段"
        }}
    ]
}}
5. change_type 只能是 modify、add、delete 之一。
6. risk 只能是 low、medium、high 之一。
7. affected_files 为可选字段；若提供，仅列出与任务相关的仓库内路径。
8. 如果信息不足，也要输出 JSON，并在 summary 中说明缺少什么资料。
"""


        response = ask_ai(prompt)


        data = extract_json_dict(response)


        if not data:

            return (
                "未能解析为结构化修改方案，模型原始输出如下：\n"
                + response
            )


        proposal = ChangeProposalList.model_validate(data)

        write_audit_event({

            "event":
            "change_proposal",

            "summary":
            proposal.summary,

            "proposal_count":
            len(proposal.proposals),

            "files":
            [
                item.file
                for item in proposal.proposals
            ],

            "affected_files":
            proposal.affected_files or [],

        })


        formatted = _format_proposal(proposal)

        return tool_success(
            SUCCESS_CODE_PROPOSAL_GENERATED,
            formatted,
            milestone=MilestoneToken.PROPOSED,
            details={
                "proposal_digest": compute_proposal_digest(formatted),
            },
        )


    except Exception as e:

        return "生成修改方案失败: " + str(e)
