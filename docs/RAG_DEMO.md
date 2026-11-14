# RAG Demo — Opt-in Hybrid Search

> **Version**: v0.10.0（RAG MVP unchanged since v0.7; `RAG_ENABLED=0` default）  
> **Type**: Usage guide (not architecture design)  
> **Design reference**: [design/rag_integration.md](design/rag_integration.md)  
> **Default**: `RAG_ENABLED=0` — identical to v0.6 search/propose behavior

## Purpose

This guide shows how to **locally enable and verify** RepoPilot's existing Repo RAG layer:

- Build the vector index with `python -m rag.build`
- Compare `search_in_repo` with `RAG_ENABLED=0` vs `1` (hybrid mode)
- Optionally inspect propose-path semantic expand (requires API key)

It does **not** change defaults, CI, or add new tools. For architecture and module layout, see [design/rag_integration.md](design/rag_integration.md).

---

## Prerequisites

Run from the **repopilot repository root** (the repo indexes itself):

```powershell
cd repopilot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
git status   # repo should be a git work tree (rag.build uses head_commit)
```

Linux / macOS: use `source .venv/bin/activate` instead of `.venv\Scripts\activate`.

**No `DEEPSEEK_API_KEY` is required** for the main demo path (build + search).

---

## Important: `.env` vs shell environment

RepoPilot reads feature flags from **process environment variables** (`config/settings.py`).

| Entry point | Loads `.env` automatically? |
|-------------|----------------------------|
| `python react_agent.py` | Yes (via `llm.load_dotenv()`) |
| `python -m rag.build` | **No** |
| `python -c "from tools.tool_manager import run_tool; ..."` | **No** |

For this demo, set flags in your **shell session**:

```powershell
# PowerShell (Windows)
$env:RAG_ENABLED = "1"
# Optional: enable AST symbol backend in hybrid merge
# $env:INDEX_ENABLED = "1"
```

```bash
# Linux / macOS
export RAG_ENABLED=1
# export INDEX_ENABLED=1
```

Adding `RAG_ENABLED=1` to `.env` alone is **not enough** for `python -m rag.build` or the `run_tool` one-liners below unless you also export it in the shell.

---

## Main path (no API key)

### Step 1 — Enable RAG for this session

```powershell
$env:RAG_ENABLED = "1"
```

Verify the flag is visible to Python:

```powershell
python -c "import config.settings as s; print('RAG_ENABLED=', s.RAG_ENABLED)"
```

Expected: `RAG_ENABLED= True`

If you skip this step, `python -m rag.build` exits with:

```text
Repo RAG is disabled (RAG_ENABLED=0)
```

### Step 2 — Build the RAG index

```powershell
python -m rag.build
```

Force a full rebuild (ignore cached `head_commit`):

```powershell
python -m rag.build --force
```

**Expected success output** (counts vary with repo size):

```text
Repo RAG build complete
repo_key: d78c5246ec1c8306...
head_commit: <current git HEAD>
rag_version: 1
built_at: <ISO timestamp>
counts: files=... chunks=...
embedding_model: mock-deterministic-v1
embedding_dim: 384
```

Artifacts are written under `database/rag_vectors/` (gitignored via `database/`).

### Step 3 (optional) — Build AST index for symbol backend

Hybrid search works without this step (grep + semantic). To include **symbol** hits in hybrid merge:

```powershell
$env:INDEX_ENABLED = "1"
python -m index.build
```

Artifacts: `database/repo_index.db`.

### Step 4 — Hybrid search (RAG on)

```powershell
$env:RAG_ENABLED = "1"
python -c "from tools.tool_manager import run_tool; print(run_tool('search_in_repo', {'keyword': 'HybridRetriever', 'extensions': '.py', 'max_results': 5}))"
```

**Expected markers:**

- Header line: `检索模式: hybrid`
- Hit lines prefixed with backend tags, e.g. `[symbol]`, `[grep]`, or `[semantic]`
- Optional score suffix: `(score=0.80)`

### Step 5 — Baseline search (RAG off)

Same command with RAG disabled:

```powershell
$env:RAG_ENABLED = "0"
python -c "from tools.tool_manager import run_tool; print(run_tool('search_in_repo', {'keyword': 'HybridRetriever', 'extensions': '.py', 'max_results': 5}))"
```

**Expected difference:**

| Aspect | `RAG_ENABLED=0` | `RAG_ENABLED=1` |
|--------|-----------------|-----------------|
| Mode line | No `检索模式: hybrid` | `检索模式: hybrid` |
| Hit format | `path:line: text` | `[backend] path:line (score=…): text` |
| Audit event | `tool_call` only | `tool_call` + `rag_query` |

### Step 6 — Audit check (optional)

After Step 4, inspect metadata-only RAG audit events:

```powershell
Get-Content logs/audit.jsonl -Tail 5
```

Look for `"event": "rag_query"` with fields such as `query_hash`, `hit_count`, `top_paths`, `backends`. No embedding vectors or full snippets are stored.

---

## Optional path — propose semantic expand (requires API key)

This step is **not required** for PR-3 acceptance. It demonstrates `RAG_CONTEXT_EXPAND` on the propose path, which calls the LLM.

**Requires:**

- `DEEPSEEK_API_KEY` in `.env` or shell
- Completed Step 2 (`python -m rag.build`)

```powershell
$env:RAG_ENABLED = "1"
# Ensure .env is loaded for the API key when using run_tool directly:
python -c "from dotenv import load_dotenv; load_dotenv(); from tools.tool_manager import run_tool; print(run_tool('propose_code_changes', {'task': 'Improve hybrid search ranking in the rag module', 'target_files': 'rag/', 'max_chars': 8000}))"
```

**What to look for:**

- Tool output: structured proposal (`===== 修改方案 =====`)
- Context loading may include `rank_source:` containing `semantic` when expand finds candidates
- Audit: optional `rag_context_expand` event (metadata: `task_hash`, `candidate_count`, `candidate_paths`)

Alternatively, use `python react_agent.py` with a readonly/full question that triggers `propose_code_changes` — `.env` is loaded automatically, but this still requires a valid API key.

---

## Turn RAG off again

```powershell
$env:RAG_ENABLED = "0"
```

Or start a new shell. Default runtime and CI remain `RAG_ENABLED=0`.

---

## Limitations (v0.7 / v0.8)

| Topic | Notes |
|-------|-------|
| Embedding | Default `mock-deterministic-v1` — CI-safe, not production semantic quality |
| Rebuild | Full rebuild only; no incremental embedding update |
| Default | `RAG_ENABLED=0` — search/propose match v0.6 when off |
| CI | Default pytest does not enable RAG |
| New tools | RAG integrates behind existing tools; ReAct tool count stays **14** |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `Repo RAG is disabled` | `RAG_ENABLED` not set in shell | `$env:RAG_ENABLED = "1"` before build |
| `.env` has `RAG_ENABLED=1` but build fails | `.env` not loaded for `rag.build` | Export in shell (see above) |
| Empty or stale semantic hits | Index not built | `python -m rag.build --force` |
| `Repo index is disabled` | `INDEX_ENABLED=0` while running `index.build` | `$env:INDEX_ENABLED = "1"` |
| propose step fails | Missing/invalid API key | Set `DEEPSEEK_API_KEY`; treat as optional |

---

## Related docs

- [design/rag_integration.md](design/rag_integration.md) — architecture and configuration reference
- [GITHUB_DEMO.md](GITHUB_DEMO.md) — core ReAct demo (RAG not required)
- [demo.md](demo.md) — full CLI/API walkthrough
- Tests: `test_rag_search_integration.py`, `test_rag_context_propose.py`
