# Verification Loop (v0.10.2)

> **Status**: **Implemented** · soft gate  
> **Tool**: `verify_change` (ReAct tool #15)  
> **Parent**: [task_mutation_state.md §7](task_mutation_state.md) · [V0.10_ROADMAP.md](../archive/V0.10_ROADMAP.md) §7

---

## 1. Placement

| Layer | Role |
|-------|------|
| **Tool** | `tools/verify_change.py` — only entry for verification |
| **TMS** | `VerificationSlice` on `TaskMutationState` — last result; **does not** advance `WorkflowSlice` |
| **FSM** | Soft: allow `verify_change` only when `workflow.state == PATCHED` |
| **Prompt** | Guide: apply → verify_change → finish |

Not a separate service/framework. No auto-fix. No pytest-by-default (avoid monorepo false fails).

---

## 2. Contract

### Args (`VerifyChangeArgs`)

| Field | Default | Meaning |
|-------|---------|---------|
| `checks` | `patched_files,syntax` | Comma-separated check ids |
| `paths` | `""` | Optional override; else TMS `artifacts.patch_applied_paths` |

### Supported checks (MVP)

| Id | Behavior |
|----|----------|
| `patched_files` | Each path exists under `REPO_ROOT`, readable, not blocked |
| `syntax` | For `.py` files: `ast.parse`; non-Python → skip that file for syntax |

### Outcomes (`ToolSuccessResult`, milestone always `null`)

| `code` | When | Workflow |
|--------|------|----------|
| `verify_passed` | All requested checks ok | stays **PATCHED** |
| `verify_failed` | Any check failed | stays **PATCHED** (no FSM rollback) |
| `verify_skipped` | No paths / nothing applicable | stays **PATCHED** |

Gate reject (structured): called before `PATCHED` → `mutation_fsm_blocked`.

---

## 3. Failure policy

- Verify fail **does not** call `git_rollback`
- Verify fail **does not** change workflow state
- Agent may finish, re-patch, or rollback via existing tools
- Audit event: `verify_change_result`

---

## 4. Checkpoint

`mutation_state_json` may include optional:

```json
"verification": {
  "status": "PASSED|FAILED|SKIPPED|NONE",
  "last_code": "verify_passed",
  "checks_run": ["patched_files", "syntax"],
  "failed_checks": [],
  "paths": ["foo.py"],
  "message": "..."
}
```

Absent/`NONE` on v0.10.0 checkpoints → hydrate as empty verification.
