"""Lightweight in-process metrics for RepoPilot observability.

Tracks:
  - Agent step count & duration (per step)
  - LLM call count & duration
  - Tool call count & duration (by tool name)
  - Total tokens consumed (from LLM API response)

Thread-safe via GIL-protected dicts — sufficient for the current single-worker
threading model.  For multi-process deployments, consider swapping to
prometheus_client + a /metrics scrape endpoint.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

# ---- In-memory metrics store ----

_metrics: dict[str, Any] = {
    # Agent
    "agent_step_count": 0,
    "agent_step_durations_ms": [],
    "agent_started_ts": None,
    # LLM
    "llm_call_count": 0,
    "llm_call_durations_ms": [],
    "llm_total_prompt_tokens": 0,
    "llm_total_completion_tokens": 0,
    # Tools
    "tool_call_count": 0,
    "tool_call_durations_ms": [],
    "tool_calls_by_name": defaultdict(int),
    # Task lifecycle
    "task_completed_count": 0,
    "task_failed_count": 0,
    "task_cancelled_count": 0,
}


def _snap(values: list) -> dict[str, Any]:
    """Return summary stats for a list of numeric values."""
    if not values:
        return {"count": 0, "min_ms": 0, "max_ms": 0, "avg_ms": 0, "total_ms": 0}
    return {
        "count": len(values),
        "min_ms": round(min(values), 1),
        "max_ms": round(max(values), 1),
        "avg_ms": round(sum(values) / len(values), 1),
        "total_ms": round(sum(values), 1),
    }


def snapshot() -> dict[str, Any]:
    """Return a JSON-serializable snapshot of current metrics."""
    return {
        "agent": {
            "step_count": _metrics["agent_step_count"],
            "step_durations": _snap(_metrics["agent_step_durations_ms"]),
        },
        "llm": {
            "call_count": _metrics["llm_call_count"],
            "call_durations": _snap(_metrics["llm_call_durations_ms"]),
            "total_prompt_tokens": _metrics["llm_total_prompt_tokens"],
            "total_completion_tokens": _metrics["llm_total_completion_tokens"],
        },
        "tools": {
            "call_count": _metrics["tool_call_count"],
            "call_durations": _snap(_metrics["tool_call_durations_ms"]),
            "by_name": dict(_metrics["tool_calls_by_name"]),
        },
        "tasks": {
            "completed": _metrics["task_completed_count"],
            "failed": _metrics["task_failed_count"],
            "cancelled": _metrics["task_cancelled_count"],
        },
    }


# ---- Recording helpers ----


def record_agent_start():
    _metrics["agent_started_ts"] = time.time()


def record_agent_step_duration(duration_ms: float):
    _metrics["agent_step_count"] += 1
    _metrics["agent_step_durations_ms"].append(duration_ms)


def record_llm_call(duration_ms: float, prompt_tokens: int = 0, completion_tokens: int = 0):
    _metrics["llm_call_count"] += 1
    _metrics["llm_call_durations_ms"].append(duration_ms)
    _metrics["llm_total_prompt_tokens"] += prompt_tokens
    _metrics["llm_total_completion_tokens"] += completion_tokens


def record_tool_call(tool_name: str, duration_ms: float):
    _metrics["tool_call_count"] += 1
    _metrics["tool_call_durations_ms"].append(duration_ms)
    _metrics["tool_calls_by_name"][tool_name] += 1


def record_task_completed():
    _metrics["task_completed_count"] += 1


def record_task_failed():
    _metrics["task_failed_count"] += 1


def record_task_cancelled():
    _metrics["task_cancelled_count"] += 1
