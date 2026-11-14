"""TaskMutationState schema v1 types (PR-M1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

TMS_SCHEMA_VERSION = 1


class MutationWorkflowState(str, Enum):
    ANALYZING = "ANALYZING"
    PROPOSED = "PROPOSED"
    DIFF_PREVIEWED = "DIFF_PREVIEWED"
    BACKED_UP = "BACKED_UP"
    PATCHED = "PATCHED"
    DONE = "DONE"


class MutationPath(str, Enum):
    NONE = "NONE"
    DIFF_FIRST = "DIFF_FIRST"
    WRITE_FALLBACK = "WRITE_FALLBACK"


class MilestoneToken(str, Enum):
    """Internal stable protocol — not user-facing; never parse message strings."""

    PROPOSED = "PROPOSED"
    DIFF_GENERATED = "DIFF_GENERATED"
    BACKUP_CREATED = "BACKUP_CREATED"
    PATCH_APPLIED = "PATCH_APPLIED"
    FILE_WRITTEN = "FILE_WRITTEN"
    ROLLBACK_TO_BACKUP = "ROLLBACK_TO_BACKUP"
    DEDUP_SKIPPED = "DEDUP_SKIPPED"


class VerificationStatus(str, Enum):
    """Separate from workflow — verify does not advance MutationWorkflowState."""

    NONE = "NONE"
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


MILESTONE_TO_WORKFLOW: dict[MilestoneToken, MutationWorkflowState] = {
    MilestoneToken.PROPOSED: MutationWorkflowState.PROPOSED,
    MilestoneToken.DIFF_GENERATED: MutationWorkflowState.DIFF_PREVIEWED,
    MilestoneToken.BACKUP_CREATED: MutationWorkflowState.BACKED_UP,
    MilestoneToken.PATCH_APPLIED: MutationWorkflowState.PATCHED,
    MilestoneToken.FILE_WRITTEN: MutationWorkflowState.PATCHED,
    MilestoneToken.ROLLBACK_TO_BACKUP: MutationWorkflowState.BACKED_UP,
}


@dataclass(frozen=True)
class BackupRef:
    backup_branch: str
    backup_commit: str
    original_branch: str
    created_at_step: int | None = None


@dataclass
class WorkflowSlice:
    state: MutationWorkflowState = MutationWorkflowState.ANALYZING
    path: MutationPath = MutationPath.NONE
    proposal_digest: str | None = None


@dataclass
class ArtifactSlice:
    backup: BackupRef | None = None
    diff_previewed_paths: list[str] = field(default_factory=list)
    patch_applied: bool = False
    patch_applied_paths: list[str] = field(default_factory=list)


@dataclass
class VerificationSlice:
    """Last verify_change result — optional; not a workflow milestone."""

    status: VerificationStatus = VerificationStatus.NONE
    last_code: str | None = None
    checks_run: list[str] = field(default_factory=list)
    failed_checks: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    message: str | None = None


@dataclass
class TaskMutationState:
    workflow: WorkflowSlice = field(default_factory=WorkflowSlice)
    artifacts: ArtifactSlice = field(default_factory=ArtifactSlice)
    verification: VerificationSlice = field(default_factory=VerificationSlice)
    epoch: int = 0
    schema_version: int = TMS_SCHEMA_VERSION


def empty_mutation_state() -> TaskMutationState:
    return TaskMutationState()


def parse_milestone_token(value: str | MilestoneToken | None) -> MilestoneToken | None:
    if value is None:
        return None
    if isinstance(value, MilestoneToken):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return MilestoneToken(text)
    except ValueError:
        return None
