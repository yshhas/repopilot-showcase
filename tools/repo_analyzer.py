import os
import re
import logging
from pathlib import Path

from config.settings import DEFAULT_LIST_MAX_RESULTS
from context.project_context import (
    get_project_name,
    get_repo_root,
    set_last_structure_report,
)
from security.path_guard import (
    is_allowed_extension,
    is_blocked_file,
    is_ignored_dir,
    resolve_repo_path,
)

logger = logging.getLogger(__name__)


KEY_FILES = {
    "README.md",
    "legacy/agent.py",
    "legacy/main.py",
    "react_agent.py",
    "llm.py",
    "schemas.py",
    "requirements.txt",
    "pyproject.toml",
    "docker-compose.yml",
    "docker-compose.yaml",
}

KEY_DIRS = {
    "tools",
    "config",
    "audit",
    "context",
    "security",
    "logs",
}



def _collect_repo_files(root: Path):

    files = []


    for current_root, dirnames, filenames in os.walk(root):

        dirnames[:] = [
            name
            for name in dirnames
            if not is_ignored_dir(name)
        ]


        for filename in filenames:

            file_path = Path(current_root) / filename


            if is_blocked_file(file_path):

                continue


            if not is_allowed_extension(file_path):

                continue


            rel = file_path.relative_to(get_repo_root())

            files.append(str(rel).replace("\\", "/"))


    return files



def analyze_repo_structure(
    path="",
    max_depth=3,
):

    try:

        root = resolve_repo_path(path)


        if not root.exists():

            return "路径不存在: " + str(path)


        repo_root = get_repo_root()

        rel_root = root.relative_to(repo_root) if root != repo_root else Path(".")

        display_root = "." if str(rel_root) == "." else str(rel_root).replace("\\", "/")


        tree_lines = []

        for current_root, dirnames, filenames in os.walk(root):

            current_path = Path(current_root)

            rel_path = current_path.relative_to(root)

            depth = len(rel_path.parts)


            if depth > max_depth:

                dirnames[:] = []

                continue


            dirnames[:] = sorted([
                name
                for name in dirnames
                if not is_ignored_dir(name)
            ])


            indent = "  " * depth

            if depth > 0:

                tree_lines.append(
                    indent
                    + current_path.name
                    + "/"
                )


            for filename in sorted(filenames):

                file_path = current_path / filename


                if is_blocked_file(file_path):

                    continue


                if not is_allowed_extension(file_path):

                    continue


                tree_lines.append(
                    indent
                    + "  "
                    + filename
                )


        all_files = _collect_repo_files(root)

        key_hits = [
            item
            for item in all_files
            if Path(item).name in KEY_FILES
        ]


        dir_stats = {}


        for item in all_files:

            top = item.split("/")[0] if "/" in item else "(root)"


            dir_stats[top] = dir_stats.get(top, 0) + 1


        lines = [

            "项目: "
            + get_project_name(),

            "分析路径: "
            + display_root,

            "文件总数: "
            + str(len(all_files)),

            "",

            "===== 目录结构 =====",

        ]


        if tree_lines:

            lines.extend(tree_lines)

        else:

            lines.append("(空目录或无允许读取的文件)")


        lines.extend([

            "",

            "===== 关键文件 =====",

        ])


        if key_hits:

            lines.extend(key_hits)

        else:

            lines.append("未识别到常见关键文件")


        lines.extend([

            "",

            "===== 模块分布 =====",

        ])


        for name in sorted(dir_stats):

            lines.append(
                name
                + ": "
                + str(dir_stats[name])
                + " 个文件"
            )


        lines.extend([

            "",

            "===== 架构提示 =====",

            "Agent 层: react_agent.py, legacy/agent.py, llm.py",

            "Tool 层: tools/tool_manager.py",

            "Schema 层: schemas.py",

            "审计层: audit/",

            "配置层: config/",

        ])


        report = "\n".join(lines)


        set_last_structure_report(report)


        return report


    except ValueError as e:

        return str(e)


    except Exception as e:

        return "分析项目结构失败: " + str(e)



def _extract_imports(content):

    imports = set()


    for line in content.splitlines():

        text = line.strip()


        if not text or text.startswith("#"):

            continue


        match = re.match(
            r"from\s+([\w\.]+)\s+import",
            text,
        )

        if match:

            imports.add(match.group(1))

            continue


        match = re.match(
            r"import\s+([\w\.]+)",
            text,
        )

        if match:

            imports.add(match.group(1))


    return sorted(imports)



def _module_candidates(rel_path):

    normalized = str(rel_path).replace("\\", "/")

    path = Path(normalized)


    if path.suffix != ".py":

        return [path.stem]


    module = str(path.with_suffix("")).replace("/", ".")


    candidates = {
        module,
        path.stem,
    }


    if "/" in normalized:

        candidates.add(normalized.split("/")[-1].replace(".py", ""))


    return sorted(candidates)



def _imports_target_file(content, candidates):

    for line in content.splitlines():

        text = line.strip()


        if not text or text.startswith("#"):

            continue


        for candidate in candidates:

            pattern = rf"(from\s+{re.escape(candidate)}\s+import|import\s+{re.escape(candidate)})"

            if re.search(pattern, text):

                return True


    return False



def _format_dependencies_report(rel_text, imports, dependents):
    lines = [
        "项目: " + get_project_name(),
        "文件: " + rel_text,
        "",
        "===== 本文件 import =====",
    ]

    if imports:
        lines.extend(imports)
    else:
        lines.append("(未识别到 import)")

    lines.extend([
        "",
        "===== 可能依赖本文件的模块 =====",
    ])

    if dependents:
        lines.extend(dependents)
    else:
        lines.append("(未发现其他文件直接 import 该模块)")

    lines.extend([
        "",
        "说明: 依赖分析基于 import 语句，属于基础静态分析。",
    ])

    return "\n".join(lines)


def _imports_target_via_index(relative_path, candidates):
    import config.settings as settings

    if not settings.INDEX_ENABLED:
        return None

    try:
        from index.query import get_file_import_hits

        hits = get_file_import_hits(relative_path, auto_build=False)
    except Exception as e:
        logger.warning("获取文件依赖失败: %s", e, exc_info=True)
        return None

    if not hits:
        return None

    pseudo_lines = []
    for hit in hits:
        module = hit.imported_module or ""
        if hit.imported_name and hit.imported_name != "*":
            pseudo_lines.append("from " + module + " import " + hit.imported_name)
        elif module:
            pseudo_lines.append("import " + module)

    if not pseudo_lines:
        return None

    pseudo_content = "\n".join(pseudo_lines)
    if _imports_target_file(pseudo_content, candidates):
        return True
    return False


def _collect_dependents_legacy_walk(file_path, rel_text, candidates, max_results):
    dependents = []

    for current_root, dirnames, filenames in os.walk(get_repo_root()):
        dirnames[:] = [
            name
            for name in dirnames
            if not is_ignored_dir(name)
        ]

        for filename in filenames:
            if not filename.endswith(".py"):
                continue

            other_path = Path(current_root) / filename

            if other_path == file_path:
                continue

            if is_blocked_file(other_path):
                continue

            other_rel = other_path.relative_to(get_repo_root())
            other_rel_text = str(other_rel).replace("\\", "/")

            matched = _imports_target_via_index(other_rel_text, candidates)

            if matched is None:
                try:
                    other_content = other_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue

                matched = _imports_target_file(other_content, candidates)

            if matched:
                dependents.append(other_rel_text)

                if len(dependents) >= max_results:
                    return dependents

        if len(dependents) >= max_results:
            break

    return dependents


def _find_file_dependencies_legacy(path, max_results=DEFAULT_LIST_MAX_RESULTS):
    file_path = resolve_repo_path(path)

    if not file_path.is_file():
        return "文件不存在: " + str(path)

    if file_path.suffix.lower() != ".py":
        return "当前仅支持 Python 文件依赖分析"

    if is_blocked_file(file_path):
        return "拒绝访问敏感文件: " + file_path.name

    content = file_path.read_text(encoding="utf-8")
    rel = file_path.relative_to(get_repo_root())
    rel_text = str(rel).replace("\\", "/")

    imports = _extract_imports(content)
    candidates = _module_candidates(rel_text)
    dependents = _collect_dependents_legacy_walk(
        file_path,
        rel_text,
        candidates,
        max_results,
    )

    return _format_dependencies_report(rel_text, imports, dependents)


def _find_symbol_dependencies(symbol, max_results=DEFAULT_LIST_MAX_RESULTS):
    import config.settings as settings

    if not settings.INDEX_ENABLED:
        return (
            "Symbol 查询不可用：repo index 未启用 (INDEX_ENABLED=0)。\n"
            "请使用 query_mode=dependencies 或启用 index。"
        )

    from audit.audit_log import write_audit_event
    from index.builder import compute_repo_key, resolve_head_commit
    from index.query import find_symbol_definitions, find_symbol_references, get_index_meta

    name = str(symbol).strip()
    definitions = find_symbol_definitions(name, limit=max_results)
    references = find_symbol_references(name, limit=max_results)
    meta = get_index_meta()

    write_audit_event({
        "event": "index_query",
        "query_mode": "symbol",
        "symbol": name,
        "definition_count": len(definitions),
        "reference_count": len(references),
        "index_version": settings.INDEX_VERSION,
        "head_commit": meta.head_commit if meta else resolve_head_commit(),
        "repo_key": compute_repo_key()[:16] + "...",
    })

    lines = [
        "Symbol 查询: " + name,
        "模式: symbol · index_version: " + str(settings.INDEX_VERSION),
    ]

    if meta and meta.head_commit:
        lines.append("head_commit: " + meta.head_commit)

    lines.extend(["", "===== 定义 (definition) ====="])

    if definitions:
        for hit in definitions:
            kind = hit.kind or "symbol"
            qual = hit.qualname or hit.symbol_name
            lines.append(
                "- "
                + hit.path
                + ":"
                + str(hit.lineno)
                + " ["
                + kind
                + "] "
                + qual
            )
    else:
        lines.append("(未找到定义)")

    lines.extend(["", "===== 引用 (reference) ====="])

    if references:
        for hit in references[:max_results]:
            context = hit.context or ""
            if context:
                lines.append("- " + hit.path + ":" + str(hit.lineno) + "  " + context)
            else:
                lines.append("- " + hit.path + ":" + str(hit.lineno))
    else:
        lines.append("(未找到引用)")

    lines.extend([
        "",
        "说明: 基于 AST 索引 (best effort)；同名 symbol 可能有多处，请结合 path+行号判断。",
    ])

    return "\n".join(lines)


def find_file_dependencies(
    path="",
    max_results=DEFAULT_LIST_MAX_RESULTS,
    symbol="",
    query_mode="auto",
):

    try:
        normalized_path = str(path).strip()
        normalized_symbol = str(symbol).strip()
        mode = str(query_mode or "auto").strip()

        if mode == "auto":
            if normalized_symbol:
                mode = "symbol"
            elif normalized_path:
                mode = "dependencies"
            else:
                return "参数错误: 需要提供 path 或 symbol"

        if mode == "symbol":
            if not normalized_symbol:
                return "参数错误: symbol 模式需要提供 symbol"
            return _find_symbol_dependencies(normalized_symbol, max_results)

        if not normalized_path:
            return "参数错误: dependencies 模式需要提供 path"

        return _find_file_dependencies_legacy(normalized_path, max_results)

    except ValueError as e:

        return str(e)

    except Exception as e:

        return "分析文件依赖失败: " + str(e)
