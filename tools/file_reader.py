from pathlib import Path

from config.settings import DEFAULT_READ_MAX_CHARS
from context.project_context import get_repo_root
from tools.repo_reader import read_repo_file



def _to_repo_relative_path(path):

    if path is None:

        return ""


    text = str(path).strip().replace("\\", "/")


    if not text:

        return ""


    path_obj = Path(text)


    if not path_obj.is_absolute():

        return text


    try:

        rel = path_obj.resolve().relative_to(get_repo_root().resolve())

    except ValueError:

        return None


    return str(rel).replace("\\", "/")



def read_file(
    path,
    max_chars=DEFAULT_READ_MAX_CHARS,
):

    relative_path = _to_repo_relative_path(path)


    if relative_path is None:

        return "拒绝访问：路径不在仓库范围内"


    return read_repo_file(
        relative_path,
        max_chars=max_chars,
    )
