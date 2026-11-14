"""ContextVar storage for TMS shadow state (PR-M1)."""

from __future__ import annotations

from contextvars import ContextVar

from context.tms.types import TaskMutationState, empty_mutation_state

_tms_shadow: ContextVar[TaskMutationState | None] = ContextVar(
    "tms_shadow",
    default=None,
)


def get_shadow() -> TaskMutationState:
    state = _tms_shadow.get()
    if state is None:
        state = empty_mutation_state()
        _tms_shadow.set(state)
    return state


def set_shadow(state: TaskMutationState) -> None:
    _tms_shadow.set(state)


def clear_shadow() -> None:
    _tms_shadow.set(empty_mutation_state())
