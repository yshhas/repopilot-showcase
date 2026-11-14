import os
from pathlib import Path

from config.settings import (
    DEFAULT_LIST_MAX_RESULTS,
    DEFAULT_READ_MAX_CHARS,
    DEFAULT_SEARCH_MAX_RESULTS,
)
from context.project_context import get_project_name, get_repo_root
from security.path_guard import (
    is_allowed_extension,
    is_blocked_file,
    is_ignored_dir,
    parse_extensions,
    resolve_repo_path,
)
from security.redaction import redact_text



def list_repo_files(
    path="",
    extensions="",
    max_results=DEFAULT_LIST_MAX_RESULTS,
):

    try:

        root = resolve_repo_path(path)

        ext_filter = parse_extensions(extensions)

        results = []


        if root.is_file():

            if is_blocked_file(root):

                return "拒绝访问敏感文件: " + root.name


            if is_allowed_extension(root, ext_filter):

                rel = root.relative_to(get_repo_root())

                return str(rel).replace("\\", "/")


            return "文件类型不在允许范围内: " + root.name


        if not root.is_dir():

            return "路径不存在: " + str(path)


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


                if not is_allowed_extension(file_path, ext_filter):

                    continue


                rel = file_path.relative_to(get_repo_root())

                results.append(str(rel).replace("\\", "/"))


                if len(results) >= max_results:

                    break


            if len(results) >= max_results:

                break


        header = (
            "项目: "
            + get_project_name()
            + "\n仓库根目录: "
            + str(get_repo_root())
            + "\n文件数量: "
            + str(len(results))
            + "\n"
        )


        if not results:

            return header + "未找到符合条件的文件"


        return header + "\n".join(results)


    except ValueError as e:

        return str(e)


    except Exception as e:

        return "列出仓库文件失败: " + str(e)



def read_repo_file(
    path,
    max_chars=DEFAULT_READ_MAX_CHARS,
):

    try:

        file_path = resolve_repo_path(path)


        if not file_path.is_file():

            return "文件不存在: " + str(path)


        if is_blocked_file(file_path):

            return "拒绝访问敏感文件: " + file_path.name


        if not is_allowed_extension(file_path):

            return "文件类型不在允许范围内: " + file_path.name


        content = file_path.read_text(
            encoding="utf-8",
        )

        content = redact_text(content)

        rel = file_path.relative_to(get_repo_root())


        header = (
            "项目: "
            + get_project_name()
            + "\n文件: "
            + str(rel).replace("\\", "/")
            + "\n"
            + "=" * 20
            + "\n"
        )


        if len(content) > max_chars:

            content = (
                content[:max_chars]
                + "\n...[内容已截断，共 "
                + str(len(content))
                + " 字符]"
            )

        return header + content


    except UnicodeDecodeError:

        return "文件不是 UTF-8 文本，暂不支持读取: " + str(path)


    except ValueError as e:

        return str(e)


    except Exception as e:

        return "读取仓库文件失败: " + str(e)



def _search_in_repo_grep_legacy(
    keyword,
    path="",
    extensions="",
    max_results=DEFAULT_SEARCH_MAX_RESULTS,
):
    root = resolve_repo_path(path)

    if root.is_file():
        pass
    elif root.is_dir():
        pass
    else:
        return "路径不存在: " + str(path)

    from rag.backends.grep_backend import format_grep_legacy_matches, grep_search_hits

    hits = grep_search_hits(
        keyword,
        path=path,
        extensions=extensions,
        max_results=max_results,
    )
    matches = format_grep_legacy_matches(hits)

    header = (
        "项目: "
        + get_project_name()
        + "\n关键词: "
        + keyword
        + "\n匹配数量: "
        + str(len(matches))
        + "\n"
    )

    if not matches:
        return header + "未找到匹配内容"

    return header + "\n".join(matches)



def _search_in_repo_hybrid(
    keyword,
    path="",
    extensions="",
    max_results=DEFAULT_SEARCH_MAX_RESULTS,
):
    import hashlib

    from audit.audit_log import write_audit_event
    from index.builder import compute_repo_key, resolve_head_commit
    from rag.hybrid import create_default_hybrid_retriever, format_hybrid_hits
    from rag.query import get_rag_meta

    root = resolve_repo_path(path)

    if not (root.is_file() or root.is_dir()):
        return "路径不存在: " + str(path)

    retriever = create_default_hybrid_retriever()
    hits = retriever.merge_rank(
        keyword,
        repo_key=compute_repo_key(),
        limit=max_results,
        path=path,
        extensions=extensions,
    )

    backend_names = sorted({item.name for item in retriever.backends})
    rag_meta = get_rag_meta()

    write_audit_event({
        "event": "rag_query",
        "query_hash": hashlib.sha256(keyword.encode("utf-8")).hexdigest()[:16],
        "hit_count": len(hits),
        "top_paths": ", ".join(hit.path for hit in hits[:10]),
        "backends": ",".join(backend_names),
        "head_commit": (rag_meta.head_commit if rag_meta else resolve_head_commit()) or "",
        "mode": "hybrid_search",
    })

    lines = format_hybrid_hits(hits)

    header = (
        "项目: "
        + get_project_name()
        + "\n关键词: "
        + keyword
        + "\n检索模式: hybrid\n"
        + "匹配数量: "
        + str(len(lines))
        + "\n"
    )

    if not lines:
        return header + "未找到匹配内容"

    return header + "\n".join(lines)



def search_in_repo(
    keyword,
    path="",
    extensions="",
    max_results=DEFAULT_SEARCH_MAX_RESULTS,
):

    try:

        if not keyword or not keyword.strip():

            return "搜索关键词不能为空"


        keyword = keyword.strip()

        import config.settings as settings

        if settings.RAG_ENABLED and settings.RAG_HYBRID_ENABLED:
            return _search_in_repo_hybrid(
                keyword,
                path=path,
                extensions=extensions,
                max_results=max_results,
            )

        return _search_in_repo_grep_legacy(
            keyword,
            path=path,
            extensions=extensions,
            max_results=max_results,
        )


    except ValueError as e:

        return str(e)


    except Exception as e:

        return "仓库搜索失败: " + str(e)
