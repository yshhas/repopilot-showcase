from config.settings import API_DEFAULT_LIST_LIMIT, API_MAX_LIST_LIMIT
from storage.task_store import get_task, init_task_db, list_tasks



def ensure_task_db():

    init_task_db()



def fetch_tasks(limit=API_DEFAULT_LIST_LIMIT):

    ensure_task_db()

    return list_tasks(limit=limit)



def fetch_task(task_id):

    ensure_task_db()

    return get_task(task_id)



def clamp_list_limit(limit):

    if limit < 1:

        return 1


    if limit > API_MAX_LIST_LIMIT:

        return API_MAX_LIST_LIMIT


    return limit
