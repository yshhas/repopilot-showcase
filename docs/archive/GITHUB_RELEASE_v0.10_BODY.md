## Summary

v0.10.0 consolidates runtime mutation state into **TaskMutationState (TMS)**. Tool outcomes advance a single TMS shadow; guards, dedup, backup resolution, and checkpoint save all read/write through TMS. v0.9 checkpoints remain resumable via v1-column hydrate.

**No new ReAct tools · No HTTP API breaking changes · Default flags unchanged**

## Highlights

- **TMS runtime SoT** — `ToolOutcome → advance_from_outcome() → TMS shadow`
- **Checkpoint v2 write** — production saves `mutation_state_json` only (v1 columns no longer updated)
- **v0.9 forward compat** — v1-only checkpoint rows still hydrate into TMS on resume
- **TMS guards** — FSM ordering + dedup skip read TMS when flags enabled
- **Task-scoped backup** — resolver flags (default off) for per-task backup SoT

## Architecture

```
ToolOutcome → advance_from_outcome() → TMS shadow
                ↓
     guards / dedup / backup (TMS readers)
                ↓
     checkpoint save → mutation_state_json
```

## Compatibility

| Item | v0.10.0 |
|------|---------|
| ReAct tools | **14** (unchanged) |
| HTTP API | unchanged |
| Default flags | unchanged (`MUTATION_FSM_ENABLED=0`, etc.) |
| v0.9 checkpoints | resume via v1 hydrate |
| Flag-off behavior | matches v0.9 for guards/dedup |

## Tests

- **497** default pytest cases passed (4 deselected live_llm)
- Golden eval **24** cases
- Legacy import policy CI check passes

## M-series commits (M1–M5)

| PR | Focus |
|----|-------|
| M1–M3 | TMS types, ToolOutcome advance, checkpoint v2 |
| M4 | Task-scoped backup |
| M5-a–f | TMS guards, v2-only save, resume shadow-only, legacy runtime removal |

Full audit: [docs/V0.10_RELEASE_AUDIT.md](V0.10_RELEASE_AUDIT.md)

## Upgrade notes

1. No API migration required.
2. New checkpoints store mutation state in `mutation_state_json`.
3. Resuming v0.9 tasks works automatically.
4. Enabling FSM/dedup flags now routes through TMS readers (recommended after this release).

## Deferred to v0.10.1+

- FSM default-on (D2)
- Dedup default-on assessment v2
- Legacy module file deletion
- `verify_change` verification loop

---

**Full changelog**: [CHANGELOG.md](../../CHANGELOG.md#0100---2026-07-21)
