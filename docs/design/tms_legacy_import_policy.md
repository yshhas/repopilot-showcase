# TMS Legacy Import Policy (PR-M1)

During M1–M4 migration, **new code must not import legacy mutation modules directly**.
All new reads/writes of mutation session state go through `context.tms`.

## Allowed to import legacy

> **Status**: **Temporary migration allowlist** (M1–M4). Reduce in M2/M3; remove in M5.

| File | Reason | Remove target |
|------|--------|---------------|
| `context/mutation_fsm.py` | legacy module itself | M5 delete |
| `context/execution_state.py` | legacy module itself | M5 delete |
| `context/project_context.py` | legacy module itself | M4/M5 |
| `context/tms/adapter.py` | **sole adapter** — reads legacy | M5 only legacy reader |
| `context/tms/advance.py` | legacy milestone mirror (PR-M2) | M5 delete mirror |
| `context/tms/backup.py` | task-scoped backup resolver (PR-M4) | M5 simplify |
| `context/tms/guards.py` | TMS FSM guard + dedup readers (PR-M5-a) | M5 default-on |
| `context/tms/resume.py` | TMS resume hint (PR-M5-d) | M5 default-on |
| `tools/outcome_schema.py` | legacy marker normalize + proposal digest | M5 delete markers |
| `tools/change_proposal.py` | proposal digest helper (existing) | M2+ refactor |
| `tools/tool_manager.py` | existing v0.9 path | **M2** migrate to `context.tms` |
| `react_agent.py` | resume/reset blocks | **M2/M3** migrate hooks |
| `test_tms_adapter.py` | TMS adapter mapping tests (legacy setup) |
| `test_tms_parity.py` | parity unit tests |
| `test_tms_sync_integration.py` | react_agent sync hook tests |
| `test_tool_result_schema.py` | structured reject tests |
| `test_mutation_fsm*.py` | legacy unit tests |
| `test_execution_state*.py` | legacy unit tests |
| `test_llm_golden.py` | golden harness |
| `test_react_cancel_checkpoint.py` | checkpoint tests |
| `storage/checkpoint_store.py` | v1 checkpoint fields until M3 |
| `api/agent_runner.py` | passes v1 blobs until M3 |

## Forbidden for new files

```python
from context.mutation_fsm import ...
from context.execution_state import ...
```

Use instead:

```python
from context.tms import build_tms_from_legacy, sync_tms_from_legacy, get_mutation_state
```

## CI enforcement

Run:

```bash
python scripts/check_no_legacy_imports.py
```

## M5 goal

Only `context/tms/adapter.py` (or its successor) may import legacy; then legacy files are deleted.
