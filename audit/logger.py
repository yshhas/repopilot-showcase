import json
import logging
from datetime import datetime, timezone

from config.settings import APP_LOG_FILE, LOG_DIR, LOG_LEVEL


_initialized = False


class JsonFormatter(logging.Formatter):


    def format(self, record):

        log_record = {

            "time":
            datetime.now(timezone.utc).isoformat(),

            "level":
            record.levelname,

            "logger":
            record.name,

            "message":
            record.getMessage(),

        }


        extra = getattr(
            record,
            "extra_fields",
            None,
        )


        if extra:

            log_record.update(extra)


        return json.dumps(
            log_record,
            ensure_ascii=False,
        )



def init_logging():


    global _initialized


    if _initialized:

        return logging.getLogger("repopilot")


    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


    logger = logging.getLogger("repopilot")

    logger.setLevel(LOG_LEVEL)

    logger.handlers.clear()


    formatter = JsonFormatter()


    file_handler = logging.FileHandler(
        APP_LOG_FILE,
        encoding="utf-8",
    )

    file_handler.setFormatter(formatter)


    console_handler = logging.StreamHandler()

    console_handler.setFormatter(formatter)


    logger.addHandler(file_handler)

    logger.addHandler(console_handler)


    logger.propagate = False


    _initialized = True


    return logger



def get_logger(name="repopilot"):

    init_logging()

    return logging.getLogger(name)
