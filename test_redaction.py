import json

from audit.audit_log import log_tool_call
from config.settings import REDACT_PLACEHOLDER
from security.redaction import (
    is_sensitive_field_name,
    redact_data,
    redact_text,
)


def test_is_sensitive_field_name():

    assert is_sensitive_field_name("api_key") is True

    assert is_sensitive_field_name("DEEPSEEK_API_KEY") is True

    assert is_sensitive_field_name("username") is False


def test_redact_text_env_line():

    raw = "DEEPSEEK_API_KEY=sk-abcdefghijklmnop\nLOG_LEVEL=INFO"

    result = redact_text(raw)

    assert "sk-abcdefghijklmnop" not in result

    assert "DEEPSEEK_API_KEY=" + REDACT_PLACEHOLDER in result

    assert "LOG_LEVEL=INFO" in result


def test_redact_text_assignment_line():

    raw = 'api_key = "super-secret-value-12345"'

    result = redact_text(raw)

    assert "super-secret-value" not in result

    assert REDACT_PLACEHOLDER in result


def test_redact_text_skips_short_assignment_values():

    raw = "token = abc"

    result = redact_text(raw)

    assert result == raw


def test_redact_text_bearer_and_sk_prefix():

    raw = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9\nkey=sk-1234567890abcdef"

    result = redact_text(raw)

    assert "eyJhbGciOi" not in result

    assert "sk-1234567890abcdef" not in result

    assert REDACT_PLACEHOLDER in result


def test_redact_data_sensitive_dict_keys():

    payload = {
        "path": "config.py",
        "api_key": "sk-live-secret-value",
        "content": "hello",
    }

    result = redact_data(payload)

    assert result["api_key"] == REDACT_PLACEHOLDER

    assert result["content"] == "hello"

    assert "sk-live-secret-value" not in json.dumps(result)


def test_audit_log_redacts_tool_call(tmp_path, monkeypatch):

    audit_file = tmp_path / "audit.jsonl"

    monkeypatch.setattr(
        "audit.audit_log.AUDIT_LOG_FILE",
        audit_file,
    )

    log_tool_call(
        "read_repo_file",
        {
            "path": "settings.py",
            "api_key": "sk-should-not-appear",
        },
        "DEEPSEEK_API_KEY=sk-leaked-in-result",
        1.0,
        task_id="redact-test",
    )

    line = audit_file.read_text(encoding="utf-8").strip()

    record = json.loads(line)

    assert "sk-should-not-appear" not in line

    assert "sk-leaked-in-result" not in line

    assert record["args"]["api_key"] == REDACT_PLACEHOLDER

    assert REDACT_PLACEHOLDER in record["result"]
