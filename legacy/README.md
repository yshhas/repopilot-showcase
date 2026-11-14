# Legacy modules

Code here is **not** part of the ReAct / HTTP main flow. It is kept for reference and local experiments.

| Path | Description |
|------|-------------|
| `agent.py` | Early RAG learning assistant (Chroma + PDF/Word/txt) |
| `main.py` | Keyword-routing demo (weather / calculator) |
| `memory.json` | Chat memory for `agent.py` |
| `tools_info.py` | Old tool prompt snippet for `main.py` |
| `scripts/manual_ai.py` | Manual LLM smoke script |
| `scripts/manual_react.py` | Manual ReAct smoke script |
| `scripts/demo_vector.py` | RAG vector-store demo (needs a local PDF) |
| `scripts/demo_split.py` | Text-splitting demo (needs a local PDF) |
| `scripts/check_env.py` | Print `TEST` from `.env` |
| `rag_helpers/` | Unused RAG helpers (`document_qa`, `document_analyzer`, `folder_reader`) |

Run from the **repository root**:

```bash
python legacy/agent.py
python legacy/main.py
python legacy/scripts/manual_react.py
```

RAG dependencies (`chromadb`, `pypdf`, `python-docx`) remain in `requirements.txt` for `legacy/agent.py`. The main ReAct agent does not require them at runtime unless you use legacy entry points.

Active RAG helpers still used by `legacy/agent.py` or registered (non-ReAct) in `tools/tool_manager.py` stay under `tools/`: `pdf_reader`, `vector_store`, `text_splitter`, `word_reader`, `text_reader`, `file_reader`.
