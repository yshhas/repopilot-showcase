from rag.chunker import chunk_python_source, chunk_repo, chunk_text_source, compute_chunk_hash


def test_chunk_python_source_extracts_class_and_functions():
    source = (
        "class FileChange:\n"
        "    def validate(self):\n"
        "        return True\n\n\n"
        "def build_change():\n"
        "    return FileChange()\n"
    )

    chunks = chunk_python_source("models.py", source)

    assert chunks
    kinds = {chunk.kind for chunk in chunks}
    assert "class" in kinds
    assert "method" in kinds
    assert "function" in kinds

    for chunk in chunks:
        assert chunk.path == "models.py"
        assert chunk.start_line >= 1
        assert chunk.end_line >= chunk.start_line
        assert chunk.chunk_hash == compute_chunk_hash(chunk.text)


def test_chunk_text_source_splits_markdown_paragraphs():
    source = "# Title\n\nFirst paragraph.\n\nSecond paragraph with more detail.\n"
    chunks = chunk_text_source("README.md", source, language="markdown")

    assert len(chunks) >= 2
    assert all(chunk.language == "markdown" for chunk in chunks)


def test_chunk_repo_respects_max_chunks(isolated_rag_repo_no_git, monkeypatch):
    import config.settings as settings

    monkeypatch.setattr(settings, "RAG_MAX_CHUNKS", 2)

    chunks, skipped = chunk_repo(isolated_rag_repo_no_git)

    assert len(chunks) == 2
    assert isinstance(skipped, list)


def test_chunk_python_source_syntax_error_falls_back_to_text():
    source = "def broken(\n"
    chunks = chunk_python_source("bad.py", source)

    assert chunks
    assert all(chunk.kind in {"text", "text_window"} for chunk in chunks)
