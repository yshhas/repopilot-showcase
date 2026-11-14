"""LLM Provider abstraction — supports any OpenAI-compatible API.

Configuration via config/settings.py environment variables:

    LLM_PROVIDER    – provider label (e.g. "deepseek", "openai", "local")
    LLM_MODEL       – model name (e.g. "deepseek-chat", "gpt-4o")
    LLM_BASE_URL    – API base URL
    LLM_API_KEY     – API key (falls back to DEEPSEEK_API_KEY)

Usage (low-level, for custom clients):

    from llm.providers import create_client

    client = create_client()
    resp = client.chat.completions.create(model=..., messages=...)

For the standard ReAct prompt + call pipeline, prefer the public APIs in
``llm.py``: ``ask_ai()`` / ``build_system_prompt()``.
"""

from __future__ import annotations

from openai import OpenAI

from config.settings import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_PROVIDER

# Provider presets for known OpenAI-compatible APIs.
_PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
    },
    "local": {
        "base_url": "http://localhost:11434/v1",
        "model": "llama3",
    },
}


def create_client(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> OpenAI:
    """Create an OpenAI-compatible client from current config.

    Respects LLM_API_KEY / LLM_BASE_URL from settings; falls back to
    DEEPSEEK_API_KEY for backward compatibility.
    """
    effective_key = api_key or LLM_API_KEY
    if not effective_key:
        raise RuntimeError(
            "LLM_API_KEY (or DEEPSEEK_API_KEY) not set — "
            "needed for LLM Provider calls"
        )

    effective_url = base_url or LLM_BASE_URL
    if not effective_url:
        raise RuntimeError(
            "LLM_BASE_URL not set — cannot create LLM client without a base URL"
        )

    return OpenAI(api_key=effective_key, base_url=effective_url)


def get_provider_info() -> dict[str, str]:
    """Return the active provider's metadata for logging/metrics."""
    return {
        "provider": LLM_PROVIDER,
        "model": LLM_MODEL,
        "base_url": LLM_BASE_URL,
    }
