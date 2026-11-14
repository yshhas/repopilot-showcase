"""TaskMutationState public API (PR-M1).

New code should import from ``context.tms`` only — not legacy mutation modules.
"""

from context.tms.advance import AdvanceResult, advance_from_outcome
from context.tms.adapter import (
    CheckpointHydrateError,
    ParityMismatchError,
    ParityResult,
    apply_checkpoint_hydrate_safe_state,
    build_tms_from_legacy,
    export_mutation_state_for_checkpoint,
    export_mutation_state_v1,
    hydrate_mutation_state_from_v1_columns,
    hydrate_mutation_state_v1,
    mirror_tms_to_legacy,
    reset_mutation_state,
    sync_tms_from_legacy,
)
from context.tms.guards import (
    build_mutation_guard_blocked_audit,
    check_mutation_allowed,
    is_dedup_guard_enabled,
    is_mutation_guard_enabled,
    is_tms_runtime_sot_enabled,
    should_use_tms_runtime_guards,
    should_skip_tool_tms,
)
from context.tms.resume import (
    build_tms_resume_hint,
    clear_tms_backup_milestones,
    user_requests_rebackup,
)
from context.tms.backup import (
    ResolvedBackupRef,
    backup_create_persistence_note,
    has_task_backup_record,
    maybe_persist_global_backup_dual_write,
    resolve_task_backup_ref,
)
from context.tms.checkpoint_hydrate import (
    HydrateDiagnostics,
    apply_checkpoint_mutation_state_to_runtime,
    hydrate_checkpoint_mutation_state,
)
from context.tms.context import get_shadow as get_mutation_state
from context.tms.parity import check_tms_parity
from context.tms.types import (
    MILESTONE_TO_WORKFLOW,
    TMS_SCHEMA_VERSION,
    ArtifactSlice,
    BackupRef,
    MilestoneToken,
    MutationPath,
    MutationWorkflowState,
    TaskMutationState,
    VerificationSlice,
    VerificationStatus,
    WorkflowSlice,
    empty_mutation_state,
    parse_milestone_token,
)

__all__ = [
    "TMS_SCHEMA_VERSION",
    "ArtifactSlice",
    "BackupRef",
    "MILESTONE_TO_WORKFLOW",
    "MilestoneToken",
    "MutationPath",
    "MutationWorkflowState",
    "ParityMismatchError",
    "ParityResult",
    "ResolvedBackupRef",
    "TaskMutationState",
    "VerificationSlice",
    "VerificationStatus",
    "WorkflowSlice",
    "CheckpointHydrateError",
    "HydrateDiagnostics",
    "backup_create_persistence_note",
    "build_tms_resume_hint",
    "build_tms_from_legacy",
    "check_tms_parity",
    "clear_tms_backup_milestones",
    "empty_mutation_state",
    "export_mutation_state_for_checkpoint",
    "export_mutation_state_v1",
    "get_mutation_state",
    "has_task_backup_record",
    "hydrate_checkpoint_mutation_state",
    "hydrate_mutation_state_from_v1_columns",
    "hydrate_mutation_state_v1",
    "maybe_persist_global_backup_dual_write",
    "mirror_tms_to_legacy",
    "parse_milestone_token",
    "reset_mutation_state",
    "resolve_task_backup_ref",
    "sync_tms_from_legacy",
    "user_requests_rebackup",
    "apply_checkpoint_hydrate_safe_state",
    "apply_checkpoint_mutation_state_to_runtime",
    "AdvanceResult",
    "advance_from_outcome",
    "build_mutation_guard_blocked_audit",
    "check_mutation_allowed",
    "is_dedup_guard_enabled",
    "is_mutation_guard_enabled",
    "is_tms_runtime_sot_enabled",
    "should_use_tms_runtime_guards",
    "should_skip_tool_tms",
]
