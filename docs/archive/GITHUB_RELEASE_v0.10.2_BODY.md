RepoPilot **v0.10.2** — Verification loop

### Highlights

- **`verify_change` ReAct tool (#15)** — post-apply checks: `patched_files` + Python `syntax`
- **TMS `VerificationSlice`** — last verify result in `mutation_state_json.verification`
- **Soft gate** — only from `PATCHED`; failure does **not** auto-rollback or change workflow
- Inherits **v0.10.1** defaults: `MUTATION_FSM_ENABLED=1`, `STRUCTURED_TOOL_REJECT_ENABLED=1` (dedup still off)

### Loop

```
propose → confirm → backup → apply_patch → verify_change → finish
```

### Tests

- **515** default pytest cases (4 deselected live_llm)
- Golden mock eval **26** cases

### Upgrade / rollback

- HTTP API unchanged
- Skip verify still allowed (soft)
- Roll back guards: `MUTATION_FSM_ENABLED=0` · `STRUCTURED_TOOL_REJECT_ENABLED=0`

Full changelog: [CHANGELOG.md](../../CHANGELOG.md) `[0.10.2]`
