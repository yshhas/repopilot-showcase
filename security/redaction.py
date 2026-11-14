import re
from typing import Any

from config.settings import (
    REDACT_PLACEHOLDER,
    SENSITIVE_ASSIGNMENT_KEYS,
    SENSITIVE_ENV_KEYS,
)


def _normalize_key(key: str) -> str:

    return str(key).lower().replace("-", "_")


def is_sensitive_field_name(key: str) -> bool:

    normalized = _normalize_key(key)

    for sensitive in SENSITIVE_ASSIGNMENT_KEYS:

        if normalized == sensitive or normalized.endswith("_" + sensitive):

            return True

    return False


def redact_field_value(key: str, value: Any) -> Any:

    if is_sensitive_field_name(key):

        return REDACT_PLACEHOLDER

    return value


def redact_text(text: str) -> str:

    if not text:

        return text

    result = text

    for env_key in SENSITIVE_ENV_KEYS:

        pattern = (
            r"("
            + re.escape(env_key)
            + r")\s*=\s*(\S+)"
        )

        result = re.sub(
            pattern,
            r"\1=" + REDACT_PLACEHOLDER,
            result,
        )

    for assign_key in SENSITIVE_ASSIGNMENT_KEYS:

        pattern = (
            r"(?i)(\b"
            + re.escape(assign_key)
            + r"\b)\s*[=:]\s*"
            r"(['\"][^'\"]{4,}['\"]|[^\s#]{8,})"
        )

        result = re.sub(
            pattern,
            r"\1=" + REDACT_PLACEHOLDER,
            result,
        )

    result = re.sub(
        r"(?i)Bearer\s+\S+",
        "Bearer " + REDACT_PLACEHOLDER,
        result,
    )

    result = re.sub(
        r"sk-[a-zA-Z0-9]{8,}",
        REDACT_PLACEHOLDER,
        result,
    )

    return result


def redact_data(data: Any) -> Any:

    if isinstance(data, dict):

        redacted = {}

        for key, value in data.items():

            if is_sensitive_field_name(key):

                redacted[key] = REDACT_PLACEHOLDER

            else:

                redacted[key] = redact_data(value)

        return redacted

    if isinstance(data, list):

        return [
            redact_data(item)
            for item in data
        ]

    if isinstance(data, str):

        return redact_text(data)

    return data
