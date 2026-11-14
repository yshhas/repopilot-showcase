"""Checkpoint hydrate entry — TMS persistence only (PR-M3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from audit.audit_log import write_audit_event
from context.tms.adapter import (
    CheckpointHydrateError,
    hydrate_mutation_state_from_v1_columns,
    hydrate_mutation_state_v1,
)
from context.tms.context import set_shadow
from context.tms.parity import check_tms_parity
from context.tms.types import TaskMutationState, empty_mutation_state


HydrateSource = Literal["v2_blob", "v1_merge", "empty"]


@dataclass(frozen=True)
class HydrateDiagnostics:
    source: HydrateSource
    derive_mismatch: bool = False
    v1_v2_divergence: bool = False
    mismatches: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    corrupted: bool = False


def _has_blob(raw: dict[str, Any] | None) -> bool:
    return bool(raw and isinstance(raw, dict))


def hydrate_checkpoint_mutation_state(
    *,
    mutation_state: dict[str, Any] | None,
    execution_state: dict[str, Any] | None,
    mutation_fsm: dict[str, Any] | None,
    task_id: str | None = None,
) -> tuple[TaskMutationState, HydrateDiagnostics]:
    """Single resume hydrate entry — no memory parsing, no advance."""
    has_v2 = _has_blob(mutation_state)
    has_v1 = _has_blob(execution_state) or _has_blob(mutation_fsm)

    if has_v2:
        try:
            state = hydrate_mutation_state_v1(mutation_state, strict=True)
        except CheckpointHydrateError as exc:
            write_audit_event(
                {
                    "event": "checkpoint_mutation_state_invalid",
                    "task_id": task_id,
                    "source": "v2_blob",
                    "error": str(exc),
                }
            )
            return empty_mutation_state(), HydrateDiagnostics(
                source="empty",
                corrupted=True,
                warnings=[str(exc)],
            )

        diagnostics = HydrateDiagnostics(source="v2_blob")

        if has_v1:
            v1_state, derive_mismatch = hydrate_mutation_state_from_v1_columns(
                mutation_fsm_json=mutation_fsm,
                execution_state_json=execution_state,
            )
            mismatches = check_tms_parity(state, v1_state)
            if mismatches:
                write_audit_event(
                    {
                        "event": "checkpoint_v1_v2_divergence",
                        "task_id": task_id,
                        "hydrate_source": "v2_blob",
                        "legacy_source": "v1_merge",
                        "mismatches": mismatches,
                        "resolution": "v2_wins",
                    }
                )
                diagnostics = HydrateDiagnostics(
                    source="v2_blob",
                    v1_v2_divergence=True,
                    mismatches=list(mismatches),
                )
            elif derive_mismatch:
                write_audit_event(
                    {
                        "event": "mutation_fsm_hydrate_mismatch",
                        "task_id": task_id,
                        "source": "v1_merge",
                        "derive_mismatch": True,
                    }
                )
                diagnostics = HydrateDiagnostics(
                    source="v2_blob",
                    derive_mismatch=True,
                )

        write_audit_event(
            {
                "event": "checkpoint_mutation_hydrated",
                "task_id": task_id,
                "source": diagnostics.source,
                "v1_v2_divergence": diagnostics.v1_v2_divergence,
                "derive_mismatch": diagnostics.derive_mismatch,
            }
        )
        return state, diagnostics

    if has_v1:
        state, derive_mismatch = hydrate_mutation_state_from_v1_columns(
            mutation_fsm_json=mutation_fsm,
            execution_state_json=execution_state,
        )
        if derive_mismatch:
            write_audit_event(
                {
                    "event": "mutation_fsm_hydrate_mismatch",
                    "task_id": task_id,
                    "source": "v1_merge",
                    "derive_mismatch": True,
                }
            )
        write_audit_event(
            {
                "event": "checkpoint_mutation_hydrated",
                "task_id": task_id,
                "source": "v1_merge",
                "derive_mismatch": derive_mismatch,
            }
        )
        return state, HydrateDiagnostics(
            source="v1_merge",
            derive_mismatch=derive_mismatch,
        )

    write_audit_event(
        {
            "event": "checkpoint_mutation_hydrated",
            "task_id": task_id,
            "source": "empty",
        }
    )
    return empty_mutation_state(), HydrateDiagnostics(source="empty")


def apply_checkpoint_mutation_state_to_runtime(
    state: TaskMutationState,
    *,
    task_id: str | None = None,
    react_step: int | None = None,
) -> None:
    """Apply hydrated TMS to runtime shadow only (PR-M5-d — no legacy mirror)."""
    set_shadow(state)
    write_audit_event(
        {
            "event": "checkpoint_mutation_applied",
            "task_id": task_id,
            "react_step": react_step,
            "workflow_state": state.workflow.state.value,
            "workflow_path": state.workflow.path.value,
            "legacy_mirrored": False,
        }
    )
