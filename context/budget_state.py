"""Per-task context budget state (ContextVar)."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class ContextBudgetState:
    chars_used: int = 0
    files_read: list[str] = field(default_factory=list)


_context_budget_state: ContextVar[ContextBudgetState | None] = ContextVar(
    "context_budget_state",
    default=None,
)


def get_context_budget_state() -> ContextBudgetState:
    state = _context_budget_state.get()
    if state is None:
        state = ContextBudgetState()
        _context_budget_state.set(state)
    return state


def reset_context_budget_state() -> None:
    _context_budget_state.set(ContextBudgetState())


def restore_context_budget_state(state: dict | None) -> None:
    if not state:
        reset_context_budget_state()
        return

    files_read = state.get("files_read")
    if not isinstance(files_read, list):
        files_read = []

    restored = ContextBudgetState(
        chars_used=int(state.get("chars_used") or 0),
        files_read=[str(item) for item in files_read],
    )
    _context_budget_state.set(restored)


def record_context_read(path: str, chars: int) -> None:
    state = get_context_budget_state()
    normalized = str(path).strip().replace("\\", "/")
    if normalized and normalized not in state.files_read:
        state.files_read.append(normalized)
    state.chars_used += max(0, chars)
