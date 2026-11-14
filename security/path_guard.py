from pathlib import Path

from config.settings import (
    ALLOWED_EXTENSIONS,
    BLOCKED_FILE_NAMES,
    BLOCKED_FILE_SUFFIXES,
    IGNORE_DIRS,
    REPO_ROOT,
)


def resolve_repo_path(relative_path=""):

    base = REPO_ROOT.resolve()


    if relative_path is None:

        relative_path = ""


    relative_path = str(relative_path).strip().replace("\\", "/")


    if relative_path in ("", "."):

        target = base

    else:

        target = (base / relative_path).resolve()


    base_text = str(base)

    target_text = str(target)


    if (
        target_text != base_text
        and not target_text.startswith(base_text + "\\")
        and not target_text.startswith(base_text + "/")
    ):

        raise ValueError("路径越界：不允许访问仓库外目录")


    return target



def is_ignored_dir(name):

    return name in IGNORE_DIRS



def path_has_ignored_segment(relative_path=""):

    if relative_path is None:

        relative_path = ""


    relative_path = str(relative_path).strip().replace("\\", "/")


    if relative_path in ("", "."):

        return False


    for part in Path(relative_path).parts:

        if part in IGNORE_DIRS:

            return True


    return False



def is_blocked_file(path: Path):

    if path.name in BLOCKED_FILE_NAMES:

        return True


    return path.suffix.lower() in BLOCKED_FILE_SUFFIXES



def is_allowed_extension(path: Path, extensions=None):

    if extensions is None:

        allowed = ALLOWED_EXTENSIONS

    else:

        allowed = extensions


    suffix = path.suffix.lower()


    if suffix == "":

        return False


    return suffix in allowed



def parse_extensions(extensions_text):

    if not extensions_text:

        return None


    items = []


    for part in extensions_text.split(","):

        part = part.strip().lower()


        if not part:

            continue


        if not part.startswith("."):

            part = "." + part


        items.append(part)


    return items or None
