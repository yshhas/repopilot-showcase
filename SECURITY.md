# Security Policy

## Supported Versions

| Version | Supported | Notes |
|---------|-----------|-------|
| **v0.10.2** | ✅ | Verification loop: `verify_change` soft gate; TMS VerificationSlice; **15** ReAct tools — [Release](docs/PROJECT_STATUS.md) |
| **v0.10.1** | ✅ | Guard default-on: `MUTATION_FSM_ENABLED=1`, `STRUCTURED_TOOL_REJECT_ENABLED=1`; dedup still off |
| **v0.10.0** | ✅ | State Consolidation: TMS runtime SoT + checkpoint v2; v0.9 hydrate compat; **14** ReAct tools |
| **v0.9.0** | ✅ | Runtime Mutation Control: opt-in FSM + structured reject |
| **v0.8.2** | ✅ | Agent engineering proof |
| **v0.8.1** | ✅ | Documentation credibility patch |
| **v0.8.0** | ✅ | execution_state dedup (opt-in) + live LLM smoke eval framework |
| **v0.7.0** | ✅ | Repo RAG MVP (hybrid search + propose expand); **`RAG_ENABLED=0` default** |
| **v0.6.0** | ✅ | Index + context budget + HTTP cancel/checkpoint resume |
| **v0.5.0** | ✅ | Multi-file batch `changes[]` on `generate_unified_diff` / `apply_patch` |
| **v0.4.0** | ✅ | Single-file unified diff preview + `apply_patch` (git apply) |
| **v0.3.0** | ⚠️ Upgrade recommended | No v0.6+ index/checkpoint or v0.7+ RAG |
| v0.2.x | ⚠️ Upgrade recommended | No v0.3.0 redaction or API Key auth |
| &lt; v0.2.0 | ❌ | No longer supported |

## Reporting a Vulnerability

If you believe you have found a security issue in RepoPilot:

1. **Do not** open a public GitHub issue for exploitable vulnerabilities.
2. Report privately via [GitHub Security Advisories](https://github.com/yshhas/repopilot-showcase/security/advisories/new) (preferred), or contact the repository owner through GitHub.
3. Include: affected version, reproduction steps, impact, and any suggested fix.

We will try to acknowledge reports within **7 days**. This is an intent, not a contractual SLA.

---

## Security Model

RepoPilot is an **enterprise repo agent** with a Git safety net and audit trail. It is **not** a sandboxed code-execution platform. Treat deployments like any service that can read/write a Git working tree.

### Repository boundary (`path_guard`)

- All repo tools resolve paths under `REPO_ROOT` (default: project root).
- Path traversal outside `REPO_ROOT` is rejected.
- **Blocked reads** (by filename/suffix): `.env`, `.env.local`, `.env.production`, `.env.development`, `credentials.json`, `secrets.json`, SSH private keys, `.pem`, `.key`, `.p12`, `.pfx`, etc. (see `config/settings.py` — not a glob matcher for every `.env*` variant).
- **Read extension allowlist** (via `read_repo_file`, `list_repo_files`, `search_in_repo`, diff preview reads): e.g. `.py`, `.md`, `.txt`, `.yaml`, `.json`, …
- **Write / patch extension allowlist**: stricter than reads — `write_repo_file` cannot write **`.json`**; `apply_patch` reuses the read allowlist for existing files, so an **existing** `.json` file can still be patched, while creating a new `.json` is rejected.
- **Write size cap**: `MAX_WRITE_BYTES` (default `100000`) applies to `new_content` / `content`.

### Human confirmation

Two layers — only the **tool-level** gate is code-enforced:

| Layer | What it is | CLI | HTTP API |
|-------|------------|-----|----------|
| **Workflow (prompt-guided)** | System prompt: `propose_code_changes` → user chat confirm → preview (recommended) → backup → apply/write | Described in `llm.py` | Same shared agent logic |
| **Tool-level (code-enforced)** | Hard block before mutation tools run | Terminal **y/n** (`security/tool_confirm.py`) | SSE `confirmation_required` + `POST /tasks/{id}/confirm` |

**`CONFIRM_REQUIRED_TOOLS`** (code-enforced): `write_repo_file`, **`apply_patch`**.

**Important:** Chat-level confirm is still prompt-guided. **v0.10.1+** also enforces mutation **tool order** when `MUTATION_FSM_ENABLED=1` (default). Tools in `CONFIRM_REQUIRED_TOOLS` always require explicit approval before execution.

`generate_unified_diff` is **read-only** and **not** confirm-gated.

### Unified diff / `apply_patch` (v0.4.0+ / v0.5 batch)

| Control | Behavior |
|---------|----------|
| **Scope** | **Single file (default)** — `path` + full `new_content`; **v0.5+** multi-file via `changes[]` on the same tools (max `PATCH_MAX_FILES`, default 10) |
| **Args** | `path`/`new_content` **XOR** `changes[]`; no mixed mode |
| **Preview** | `generate_unified_diff` rebuilds diff from disk + `new_content`; does not write files or run git |
| **No raw LLM diff** | Prompt forbids pasting executable unified diff; apply path uses tools only |
| **Backup** | Default `PATCH_REQUIRE_BACKUP=1` — `apply_patch` **rejects** without `git_create_backup` record |
| **Validation** | Rebuild diff at apply time; hunk/line limits (`PATCH_MAX_HUNKS`, `PATCH_MAX_CHANGED_LINES`) |
| **Git apply** | `git apply --check` then `git apply`; `subprocess` list args, `cwd=REPO_ROOT`, **no** `shell=True` |
| **Failure** | **No auto-rollback** inside `apply_patch`; agent flow should call `git_rollback` |
| **Audit** | `diff_preview` stores **summary stats only** (no full diff, no `new_content`); `patch_apply` records path/status/stats/backup metadata |

### `write_repo_file` (v0.3 compatible fallback)

- Whole-file overwrite remains available as **alternative** to `apply_patch`.
- No backup **requirement** at code level (warns if no backup record).
- Same extension whitelist and `MAX_WRITE_BYTES` as patch path.

### Runtime modes (`AGENT_MODE`)

| Mode | Read/analyze | `propose_code_changes` | `generate_unified_diff` | Git / write / patch |
|------|--------------|------------------------|-------------------------|---------------------|
| `full` | ✅ | ✅ | ✅ preview | ✅ `git_create_backup`, `apply_patch`, `write_repo_file`, `git_rollback` (with confirmation where required) |
| `readonly` | ✅ | ✅ | ✅ preview only | ❌ blocked |

Per-task `mode` on `POST /tasks` overrides the server default when set.

### Read-path redaction (v0.3.0 P1)

- `security/redaction.py` redacts sensitive patterns in **tool output** and **audit JSONL** (env assignments, Bearer tokens, `sk-` prefixes, sensitive field names).
- This is **pattern-based redaction**, not full DLP. Do not rely on it as the only control for classified data.

### HTTP API authentication (v0.3.0 P2)

- Optional `API_KEY` environment variable.
- When set, all routes except `GET /health` require header `X-API-Key: <API_KEY>`.
- When unset or blank, auth is **disabled** (development-friendly default — **not** safe for public exposure).
- No OAuth, JWT, or user accounts.

### Git backup and rollback

- `git_create_backup` creates a local backup branch; state stored in `logs/last_backup.json`.
- `git_rollback` runs **`git reset --hard`** — destructive and irreversible for uncommitted work.
- Only the **most recent** backup is tracked.

### Audit and secrets in logs

- Tool calls and ReAct steps append to `logs/audit.jsonl`.
- Fields are redacted then truncated (`AUDIT_MAX_FIELD_LENGTH`, default 500 chars).
- **`diff_preview` events intentionally omit full diff text** to reduce secret leakage in audit logs.
- **Do not** point `REPO_ROOT` at repositories containing production secrets unless path blocks and redaction are sufficient for your threat model.

### LLM and third parties

- LLM calls use `DEEPSEEK_API_KEY` (DeepSeek API). Prompts may include repo file contents the agent reads.
- Review your data-handling policy before sending proprietary code to external LLM providers.

---

## Deployment Recommendations

These are **operator guidelines**, not features RepoPilot enforces automatically:

| Scenario | Recommendation |
|----------|----------------|
| Local development | Default (no `API_KEY`) is acceptable on `127.0.0.1` |
| Shared / staging API | Set `API_KEY`; bind to internal network; terminate TLS at a reverse proxy |
| Production | Set `API_KEY`; restrict network access; use `AGENT_MODE=readonly` for analysis-only workloads; monitor `logs/audit.jsonl` |
| Docker | Container uses an **independent** Git baseline — not your host `.git` |
| Secrets | Keep `.env` out of the repo; never commit API keys |

---

## Known Limitations (not bugs)

Documented product boundaries:

- **Diff / patch scope** — single file default (`path` + `new_content`); **v0.5+** multi-file via `changes[]` on the same tools (max `PATCH_MAX_FILES`, default 10); no merge/conflict UI
- **Whole-file fallback** — `write_repo_file` still overwrites entire files (single-file only)
- **No sandbox** — agent runs with process privileges on `REPO_ROOT`
- **Optional API auth** — must be explicitly enabled for HTTP hardening
- **Redaction ≠ DLP** — sensitive data may still exist in LLM context or misconfigured paths
- **Mutation ordering** — v0.10.1 defaults enforce FSM tool order (`MUTATION_FSM_ENABLED=1`); backup-before-apply also enforced for `apply_patch` when `PATCH_REQUIRE_BACKUP=1`; `write_repo_file` backup remains warn-only
- **Legacy RAG code** under `legacy/` — separate from the ReAct main flow; not hardened for production document ingestion

---

## Security-related tests

Automated coverage includes (among **505** CI pytest cases / **525** full local suite; **4** opt-in live smoke cases excluded):

- `test_file_reader_security.py` — path blocks, ReAct tool exposure
- `test_diff_security.py` / `test_patch_apply.py` / `test_apply_patch_tool.py` — readonly, confirm, backup, subprocess safety
- `test_redaction.py` — redaction patterns
- `test_api_auth.py` — API Key middleware
- `test_agent_mode.py` — readonly mutation blocking
- `test_task_report.py` — diff/patch audit summaries without raw diff in reports
- `test_execution_state_*.py` / `test_tms_*.py` / `test_mutation_fsm*.py` — TMS / FSM / dedup (opt-in flags)
- `tests/live_llm/` — live LLM smoke eval (manual opt-in only)

Run locally:

```powershell
python -m pytest -v
```

---

## Related documentation

- [README.md — 安全说明](README.md#安全说明)
- [docs/architecture.md](docs/architecture.md)
- [docs/workflow.md](docs/workflow.md)
- [CHANGELOG.md](CHANGELOG.md)
