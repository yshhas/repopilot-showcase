import json
from datetime import datetime, timezone

from config.settings import BACKUP_STATE_FILE, LOG_DIR, REPO_ROOT


_last_structure_report = None

_last_backup_branch = None

_last_backup_commit = None

_last_original_branch = None



def get_repo_root():

    return REPO_ROOT



def get_project_name():

    return REPO_ROOT.name



def set_last_structure_report(report):

    global _last_structure_report

    _last_structure_report = report



def get_last_structure_report():

    return _last_structure_report



def _load_backup_from_disk():

    global _last_backup_branch

    global _last_backup_commit

    global _last_original_branch


    if not BACKUP_STATE_FILE.exists():

        return


    try:

        data = json.loads(
            BACKUP_STATE_FILE.read_text(
                encoding="utf-8",
            )
        )

    except (OSError, json.JSONDecodeError):

        return


    if not isinstance(data, dict):

        return


    if data.get("repo_root") != str(REPO_ROOT):

        return


    _last_backup_branch = data.get("backup_branch")

    _last_backup_commit = data.get("backup_commit")

    _last_original_branch = data.get("original_branch")



def _save_backup_to_disk():

    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


    data = {

        "repo_root":
        str(REPO_ROOT),

        "backup_branch":
        _last_backup_branch,

        "backup_commit":
        _last_backup_commit,

        "original_branch":
        _last_original_branch,

        "updated_at":
        datetime.now(timezone.utc).isoformat(),

    }


    BACKUP_STATE_FILE.write_text(

        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),

        encoding="utf-8",

    )



def _ensure_backup_loaded():

    if _last_backup_branch or _last_backup_commit:
        return

    _load_backup_from_disk()


def _reset_backup_global_state():
    """Reset cached backup globals — used between isolated test repos."""
    global _last_backup_branch, _last_backup_commit, _last_original_branch
    _last_backup_branch = None
    _last_backup_commit = None
    _last_original_branch = None



def set_backup_info(
    backup_branch,
    backup_commit,
    original_branch,
):
    """Persist global backup metadata (deprecated for task-scoped flows — PR-M4)."""

    global _last_backup_branch

    global _last_backup_commit

    global _last_original_branch


    _last_backup_branch = backup_branch

    _last_backup_commit = backup_commit

    _last_original_branch = original_branch


    _save_backup_to_disk()



def get_backup_branch():

    _ensure_backup_loaded()

    return _last_backup_branch



def get_backup_commit():

    _ensure_backup_loaded()

    return _last_backup_commit



def get_original_branch():

    _ensure_backup_loaded()

    return _last_original_branch



def get_backup_info():

    _ensure_backup_loaded()


    return {

        "repo_root": str(REPO_ROOT),

        "backup_branch": _last_backup_branch,

        "backup_commit": _last_backup_commit,

        "original_branch": _last_original_branch,

        "state_file": str(BACKUP_STATE_FILE),

    }
