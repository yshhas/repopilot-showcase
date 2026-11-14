"""AST-aware and fallback chunking for repo RAG (v0.7 C1)."""

from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path

import config.settings as settings
from rag.models import CodeChunk
from security.path_guard import (
    is_allowed_extension,
    is_blocked_file,
    is_ignored_dir,
    resolve_repo_path,
)


def compute_chunk_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _format_chunk_text(
    *,
    path: str,
    symbol_name: str | None,
    kind: str,
    start_line: int,
    end_line: int,
    body: str,
) -> str:
    header_lines = [
        "# path: " + path,
        "# kind: " + kind,
        "# lines: " + str(start_line) + "-" + str(end_line),
    ]
    if symbol_name:
        header_lines.insert(2, "# symbol: " + symbol_name + " (" + kind + ")")

    return "\n".join(header_lines) + "\n\n" + body.strip()


def _make_chunk(
    *,
    path: str,
    start_line: int,
    end_line: int,
    body: str,
    symbol_name: str | None,
    kind: str,
    language: str,
) -> CodeChunk:
    text = _format_chunk_text(
        path=path,
        symbol_name=symbol_name,
        kind=kind,
        start_line=start_line,
        end_line=end_line,
        body=body,
    )
    return CodeChunk(
        path=path,
        start_line=start_line,
        end_line=end_line,
        text=text,
        symbol_name=symbol_name,
        kind=kind,
        language=language,
        chunk_hash=compute_chunk_hash(text),
    )


def _extract_lines(source_lines: list[str], start_line: int, end_line: int) -> str:
    start_index = max(0, start_line - 1)
    end_index = min(len(source_lines), end_line)
    return "\n".join(source_lines[start_index:end_index])


class _PythonChunkVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str, source_lines: list[str]):
        self.relative_path = relative_path
        self.source_lines = source_lines
        self.chunks: list[CodeChunk] = []
        self._class_stack: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        self._append_node_chunk(node, symbol_name=None, kind="imports")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._append_node_chunk(node, symbol_name=None, kind="imports")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        end_line = getattr(node, "end_lineno", node.lineno)
        body = _extract_lines(self.source_lines, node.lineno, end_line)
        self.chunks.append(
            _make_chunk(
                path=self.relative_path,
                start_line=node.lineno,
                end_line=end_line,
                body=body,
                symbol_name=node.name,
                kind="class",
                language="python",
            )
        )

        self._class_stack.append(node.name)
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._append_function_chunk(child, parent_class=node.name)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if not self._class_stack:
            self._append_function_chunk(node, parent_class=None)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if not self._class_stack:
            self._append_function_chunk(node, parent_class=None)

    def _append_function_chunk(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        parent_class: str | None,
    ) -> None:
        end_line = getattr(node, "end_lineno", node.lineno)
        body = _extract_lines(self.source_lines, node.lineno, end_line)
        if parent_class:
            kind = "method"
            symbol_name = parent_class + "." + node.name
        else:
            kind = "function"
            symbol_name = node.name

        line_count = end_line - node.lineno + 1
        if line_count > 120:
            self._append_window_chunks(
                body=body,
                start_line=node.lineno,
                symbol_name=symbol_name,
                kind=kind,
                window_size=60,
                overlap=20,
            )
            return

        self.chunks.append(
            _make_chunk(
                path=self.relative_path,
                start_line=node.lineno,
                end_line=end_line,
                body=body,
                symbol_name=symbol_name,
                kind=kind,
                language="python",
            )
        )

    def _append_node_chunk(
        self,
        node: ast.AST,
        *,
        symbol_name: str | None,
        kind: str,
    ) -> None:
        end_line = getattr(node, "end_lineno", node.lineno)
        body = _extract_lines(self.source_lines, node.lineno, end_line)
        self.chunks.append(
            _make_chunk(
                path=self.relative_path,
                start_line=node.lineno,
                end_line=end_line,
                body=body,
                symbol_name=symbol_name,
                kind=kind,
                language="python",
            )
        )

    def _append_window_chunks(
        self,
        *,
        body: str,
        start_line: int,
        symbol_name: str | None,
        kind: str,
        window_size: int,
        overlap: int,
    ) -> None:
        lines = body.splitlines()
        if not lines:
            return

        step = max(1, window_size - overlap)
        for offset in range(0, len(lines), step):
            window = lines[offset : offset + window_size]
            if not window:
                continue

            chunk_start = start_line + offset
            chunk_end = chunk_start + len(window) - 1
            self.chunks.append(
                _make_chunk(
                    path=self.relative_path,
                    start_line=chunk_start,
                    end_line=chunk_end,
                    body="\n".join(window),
                    symbol_name=symbol_name,
                    kind=kind + "_window",
                    language="python",
                )
            )


def chunk_python_source(relative_path: str, source: str) -> list[CodeChunk]:
    rel_text = str(relative_path).replace("\\", "/")
    source_lines = source.splitlines()

    try:
        tree = ast.parse(source, filename=rel_text)
    except SyntaxError:
        return chunk_text_source(rel_text, source, language="python")

    visitor = _PythonChunkVisitor(rel_text, source_lines)
    visitor.visit(tree)

    if visitor.chunks:
        return _dedupe_chunks(visitor.chunks)

    return chunk_text_source(rel_text, source, language="python")


def chunk_text_source(
    relative_path: str,
    source: str,
    *,
    language: str = "text",
    max_chars: int = 800,
) -> list[CodeChunk]:
    rel_text = str(relative_path).replace("\\", "/")
    paragraphs: list[tuple[int, int, str]] = []
    buffer: list[str] = []
    buffer_start = 1

    for index, line in enumerate(source.splitlines(), start=1):
        if not line.strip():
            if buffer:
                paragraphs.append((buffer_start, index - 1, "\n".join(buffer)))
                buffer = []
            continue

        if not buffer:
            buffer_start = index
        buffer.append(line)

    if buffer:
        paragraphs.append((buffer_start, len(source.splitlines()), "\n".join(buffer)))

    if not paragraphs and source.strip():
        paragraphs.append((1, max(1, len(source.splitlines())), source.strip()))

    chunks: list[CodeChunk] = []
    for start, end, body in paragraphs:
        if len(body) <= max_chars:
            chunks.append(
                _make_chunk(
                    path=rel_text,
                    start_line=start,
                    end_line=end,
                    body=body,
                    symbol_name=None,
                    kind="text",
                    language=language,
                )
            )
            continue

        text_lines = body.splitlines()
        current: list[str] = []
        current_chars = 0
        chunk_start = start

        for offset, line in enumerate(text_lines):
            line_len = len(line) + 1
            if current and current_chars + line_len > max_chars:
                chunk_end = chunk_start + len(current) - 1
                chunks.append(
                    _make_chunk(
                        path=rel_text,
                        start_line=chunk_start,
                        end_line=chunk_end,
                        body="\n".join(current),
                        symbol_name=None,
                        kind="text_window",
                        language=language,
                    )
                )
                current = [line]
                current_chars = line_len
                chunk_start = start + offset
                continue

            current.append(line)
            current_chars += line_len

        if current:
            chunk_end = chunk_start + len(current) - 1
            chunks.append(
                _make_chunk(
                    path=rel_text,
                    start_line=chunk_start,
                    end_line=chunk_end,
                    body="\n".join(current),
                    symbol_name=None,
                    kind="text_window",
                    language=language,
                )
            )

    return _dedupe_chunks(chunks)


def chunk_sliding_window_source(
    relative_path: str,
    source: str,
    *,
    language: str,
    window_size: int = 60,
    overlap: int = 20,
) -> list[CodeChunk]:
    rel_text = str(relative_path).replace("\\", "/")
    lines = source.splitlines()
    if not lines:
        return []

    chunks: list[CodeChunk] = []
    step = max(1, window_size - overlap)

    for offset in range(0, len(lines), step):
        window = lines[offset : offset + window_size]
        if not window:
            continue

        start_line = offset + 1
        end_line = start_line + len(window) - 1
        chunks.append(
            _make_chunk(
                path=rel_text,
                start_line=start_line,
                end_line=end_line,
                body="\n".join(window),
                symbol_name=None,
                kind="window",
                language=language,
            )
        )

    return _dedupe_chunks(chunks)


def _dedupe_chunks(chunks: list[CodeChunk]) -> list[CodeChunk]:
    seen: set[str] = set()
    unique: list[CodeChunk] = []

    for chunk in chunks:
        if chunk.chunk_hash in seen:
            continue
        seen.add(chunk.chunk_hash)
        unique.append(chunk)

    return unique


def _language_for_suffix(suffix: str) -> str:
    mapping = {
        ".py": "python",
        ".md": "markdown",
        ".txt": "text",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".toml": "toml",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".vue": "vue",
        ".html": "html",
        ".css": "css",
    }
    return mapping.get(suffix.lower(), "text")


def chunk_file(repo_root: Path, relative_path: Path) -> list[CodeChunk]:
    file_path = repo_root / relative_path
    rel_text = str(relative_path).replace("\\", "/")

    try:
        raw = file_path.read_bytes()
    except OSError:
        return []

    if len(raw) > settings.RAG_MAX_FILE_BYTES:
        return []

    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError:
        return []

    suffix = file_path.suffix.lower()
    if suffix == ".py":
        return chunk_python_source(rel_text, source)

    if suffix in {".md", ".txt"}:
        return chunk_text_source(rel_text, source, language=_language_for_suffix(suffix))

    if suffix in {".yaml", ".yml", ".json", ".toml"}:
        if len(source) <= 2000:
            return chunk_text_source(rel_text, source, language=_language_for_suffix(suffix), max_chars=2000)
        return chunk_text_source(rel_text, source, language=_language_for_suffix(suffix))

    return chunk_sliding_window_source(
        rel_text,
        source,
        language=_language_for_suffix(suffix),
    )


def iter_indexable_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []

    for current_root, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [name for name in dirnames if not is_ignored_dir(name)]

        for filename in filenames:
            file_path = Path(current_root) / filename

            if is_blocked_file(file_path):
                continue

            if not is_allowed_extension(file_path):
                continue

            rel = file_path.relative_to(repo_root)
            files.append(rel)

    return sorted(files, key=lambda item: str(item))


def chunk_repo(repo_root: Path | None = None) -> tuple[list[CodeChunk], list[str]]:
    root = (repo_root or settings.REPO_ROOT).resolve()
    chunks: list[CodeChunk] = []
    skipped_files: list[str] = []

    for relative_path in iter_indexable_files(root):
        rel_text = str(relative_path).replace("\\", "/")

        try:
            resolve_repo_path(rel_text)
        except ValueError:
            skipped_files.append(rel_text)
            continue

        file_chunks = chunk_file(root, relative_path)
        if not file_chunks:
            skipped_files.append(rel_text)
            continue

        for chunk in file_chunks:
            chunks.append(chunk)
            if len(chunks) >= settings.RAG_MAX_CHUNKS:
                return chunks, skipped_files

    return chunks, skipped_files
