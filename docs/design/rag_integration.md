# RepoPilot RAG Integration Design (v0.7.0)

> **Status**: **Implemented** · PR-RC 2026-07-20  
> **Baseline**: v0.6.0 (tag `v0.6.0`) · 284 pytest  
> **Implementation**: C1 (rag kernel) ✅ · C2 (hybrid search) ✅ · C3 (propose expand) ✅  
> **Related**: [V0.7_ROADMAP.md](../archive/V0.7_ROADMAP.md) · [repo_index.md](repo_index.md) · [architecture.md](../architecture.md)

---

## English Summary

RepoPilot **v0.7.0** adds **semantic retrieval as an enhancement layer** for the code repo Agent. RAG complements the v0.6 **AST index** (structure) with vector similarity (natural language / similar code). It integrates **behind existing tools** — no new ReAct tools. Default **`RAG_ENABLED=0`** preserves full v0.6 behavior.

---

## 1. Goals

| Goal | v0.7 |
|------|------|
| Similar code retrieval | ✅ SemanticBackend + Chroma |
| Related implementation retrieval | ✅ Hybrid merge in `search_in_repo` |
| Propose context enrichment | ✅ task → semantic candidates → ranking |
| Index as ground truth | ✅ SymbolBackend; RAG does not replace Index |
| v0.6 compatibility | ✅ `RAG_ENABLED=0` default |

## 2. Non-goals (v0.7.0)

| Deferred | Notes |
|----------|-------|
| Chat / PDF knowledge base | Legacy `legacy/agent.py` unchanged |
| Production embedding model | Mock default; Chroma provider available |
| Incremental embedding | Full rebuild only |
| History task RAG | No audit memory indexing |
| JS/TS AST chunking | Sliding window fallback |
| New ReAct tools | Tool count stays **14** |

---

## 3. Architecture

```
ReAct Agent
    ├── search_in_repo ──► HybridRetriever (when RAG_ENABLED=1)
    │                         ├── GrepBackend
    │                         ├── SymbolBackend (INDEX_ENABLED)
    │                         └── SemanticBackend
    └── propose_code_changes ──► context budget ranking
                                    ├── affected_files / target_files / deps (v0.6)
                                    └── semantic expand from task (v0.7)
                                          └── read_repo_file (not chunk text)
```

**Storage**:

| Store | Path | Purpose |
|-------|------|---------|
| `repo_index.db` | `database/repo_index.db` | AST structure (v0.6) |
| `rag_vectors/` | `database/rag_vectors/` | Chroma embeddings (v0.7) |

---

## 4. Module layout

```
rag/
  models.py           CodeChunk, RagMeta, RagHit
  chunker.py          AST-aware + fallback chunking
  embedder.py         MockEmbeddingProvider (+ Chroma optional)
  store.py            Chroma PersistentClient
  builder.py          build_rag_index()
  query.py            semantic_search()
  context_expand.py   propose path semantic candidates
  hybrid.py           HybridRetriever
  backends/           grep, symbol, semantic
  build/__main__.py   python -m rag.build
```

---

## 5. Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RAG_ENABLED` | `0` | Master switch; `0` = v0.6 behavior |
| `RAG_AUTO_REBUILD` | `1` | Lazy rebuild on `head_commit` change |
| `RAG_HYBRID_ENABLED` | `1` | Hybrid merge in `search_in_repo` |
| `RAG_CONTEXT_EXPAND` | `1` | Semantic expand in propose path |
| `RAG_VECTOR_DIR` | `database/rag_vectors` | Chroma persist dir |
| `RAG_EMBEDDING_MODEL` | `mock-deterministic-v1` | CI-safe mock default |

---

## 6. Ranking weights (propose path)

| Signal | Weight |
|--------|--------|
| `affected_files` | 100 |
| `target_files` | 95 |
| `dependency_*` | 55–95 |
| `symbol_*` | 80–90 |
| `semantic` | 50–70 (scaled) |

Semantic never overrides explicit `affected_files`.

---

## 7. Audit events

| Event | When | Fields (metadata only) |
|-------|------|------------------------|
| `rag_query` | hybrid `search_in_repo` | `query_hash`, `hit_count`, `top_paths`, `backends` |
| `rag_context_expand` | propose semantic expand | `task_hash`, `candidate_count`, `candidate_paths` |
| `context_budget_applied` | unchanged | may include `semantic` in `rank_source` |

No embedding vectors or full file bodies in JSONL.

---

## 8. Acceptance (v0.7.0)

- [x] `python -m rag.build` produces Chroma index + meta
- [x] `RAG_ENABLED=0` → search + propose identical to v0.6
- [x] Hybrid `search_in_repo` when `RAG_ENABLED=1`
- [x] Propose semantic expand merges into ranking; loads via `read_repo_file`
- [x] ReAct tools = **14**
- [x] pytest **313+** at RC
- [x] Golden **16** cases

---

## 9. Document history

| Date | Status | Notes |
|------|--------|-------|
| 2026-07-20 | Draft | Initial design review |
| 2026-07-20 | **Implemented** | C1+C2+C3 + PR-RC |
