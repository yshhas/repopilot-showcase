"""Build repo index from Python AST (v0.6 C1)."""

from __future__ import annotations

import ast
import hashlib
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import config.settings as settings
from index.models import ImportRecord, IndexMeta, ReferenceRecord, SymbolRecord
from index.store import (
    clear_repo_index,
    connect,
    insert_imports,
    insert_references,
    insert_symbols,
    is_index_enabled,
    load_index_meta,
    save_index_meta,
)
from security.path_guard import is_allowed_extension, is_blocked_file, is_ignored_dir


@dataclass
class BuildResult:
    ok: bool
    repo_key: str
    meta: IndexMeta | None = None
    error: str | None = None
    skipped_files: list[str] | None = None


def compute_repo_key(repo_root: Path | None = None) -> str:
    root = (repo_root or settings.REPO_ROOT).resolve()
    return hashlib.sha256(str(root).encode("utf-8")).hexdigest()


def resolve_head_commit(repo_root: Path | None = None) -> str | None:
    root = repo_root or settings.REPO_ROOT
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError:
        return None

    if completed.returncode != 0:
        return None

    value = (completed.stdout or "").strip()
    return value or None


def needs_rebuild(repo_root: Path | None = None) -> bool:
    if not is_index_enabled():
        return False

    root = (repo_root or settings.REPO_ROOT).resolve()
    repo_key = compute_repo_key(root)

    with connect() as conn:
        meta = load_index_meta(conn, repo_key)

    if meta is None:
        return True

    if not settings.INDEX_AUTO_REBUILD:
        return False

    current_head = resolve_head_commit(root)
    return meta.head_commit != current_head


def _truncate_context(text: str, limit: int = 200) -> str:
    from context._shared import truncate_text
    return truncate_text(text.strip(), limit)


def _iter_python_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []

    for current_root, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [name for name in dirnames if not is_ignored_dir(name)]

        for filename in filenames:
            file_path = Path(current_root) / filename

            if is_blocked_file(file_path):
                continue

            if file_path.suffix.lower() != ".py":
                continue

            if not is_allowed_extension(file_path):
                continue

            rel = file_path.relative_to(repo_root)
            files.append(rel)

    return sorted(files, key=lambda item: str(item))


class _DefinitionVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str):
        self.relative_path = relative_path
        self.symbols: list[SymbolRecord] = []
        self._class_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualname = node.name
        self.symbols.append(
            SymbolRecord(
                path=self.relative_path,
                name=node.name,
                kind="class",
                lineno=node.lineno,
                end_lineno=getattr(node, "end_lineno", None),
                qualname=qualname,
            )
        )
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record_function(node)

    def _record_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if self._class_stack:
            kind = "method"
            qualname = self._class_stack[-1] + "." + node.name
        else:
            kind = "function"
            qualname = node.name

        self.symbols.append(
            SymbolRecord(
                path=self.relative_path,
                name=node.name,
                kind=kind,
                lineno=node.lineno,
                end_lineno=getattr(node, "end_lineno", None),
                qualname=qualname,
            )
        )


class _ReferenceVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str, source_lines: list[str]):
        self.relative_path = relative_path
        self.source_lines = source_lines
        self.references: list[ReferenceRecord] = []

    def visit_Name(self, node: ast.Name) -> None:
        if not isinstance(node.ctx, ast.Load):
            return

        line_index = node.lineno - 1
        context = ""
        if 0 <= line_index < len(self.source_lines):
            context = _truncate_context(self.source_lines[line_index])

        self.references.append(
            ReferenceRecord(
                path=self.relative_path,
                symbol_name=node.id,
                lineno=node.lineno,
                col_offset=node.col_offset,
                context=context,
            )
        )


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str):
        self.relative_path = relative_path
        self.imports: list[ImportRecord] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(
                ImportRecord(
                    path=self.relative_path,
                    imported_module=alias.name,
                    imported_name=alias.asname or alias.name.split(".")[-1],
                    lineno=node.lineno,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if node.level:
            prefix = "." * node.level
            module = prefix + module

        if not node.names:
            self.imports.append(
                ImportRecord(
                    path=self.relative_path,
                    imported_module=module,
                    imported_name=None,
                    lineno=node.lineno,
                )
            )
            return

        for alias in node.names:
            if alias.name == "*":
                imported_name = "*"
            else:
                imported_name = alias.asname or alias.name

            self.imports.append(
                ImportRecord(
                    path=self.relative_path,
                    imported_module=module,
                    imported_name=imported_name,
                    lineno=node.lineno,
                )
            )


def _parse_python_file(
    repo_root: Path,
    relative_path: Path,
) -> tuple[list[SymbolRecord], list[ReferenceRecord], list[ImportRecord]] | None:
    file_path = repo_root / relative_path
    rel_text = str(relative_path).replace("\\", "/")

    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    try:
        tree = ast.parse(source, filename=rel_text)
    except SyntaxError:
        return None

    source_lines = source.splitlines()

    definition_visitor = _DefinitionVisitor(rel_text)
    definition_visitor.visit(tree)

    reference_visitor = _ReferenceVisitor(rel_text, source_lines)
    reference_visitor.visit(tree)

    import_visitor = _ImportVisitor(rel_text)
    import_visitor.visit(tree)

    return (
        definition_visitor.symbols,
        reference_visitor.references,
        import_visitor.imports,
    )


def build_index(
    repo_root: Path | None = None,
    *,
    force: bool = False,
) -> BuildResult:
    if not is_index_enabled():
        return BuildResult(
            ok=False,
            repo_key="",
            error="Repo index is disabled (INDEX_ENABLED=0)",
        )

    root = (repo_root or settings.REPO_ROOT).resolve()
    repo_key = compute_repo_key(root)

    if not force and not needs_rebuild(root):
        with connect() as conn:
            meta = load_index_meta(conn, repo_key)
        return BuildResult(ok=True, repo_key=repo_key, meta=meta)

    python_files = _iter_python_files(root)
    all_symbols: list[SymbolRecord] = []
    all_references: list[ReferenceRecord] = []
    all_imports: list[ImportRecord] = []
    skipped: list[str] = []

    for relative_path in python_files:
        parsed = _parse_python_file(root, relative_path)
        rel_text = str(relative_path).replace("\\", "/")

        if parsed is None:
            skipped.append(rel_text)
            continue

        symbols, references, imports = parsed
        all_symbols.extend(symbols)
        all_references.extend(references)
        all_imports.extend(imports)

    built_at = datetime.now(timezone.utc).isoformat()
    head_commit = resolve_head_commit(root)

    meta = IndexMeta(
        repo_key=repo_key,
        head_commit=head_commit,
        index_version=settings.INDEX_VERSION,
        built_at=built_at,
        file_count=len(python_files) - len(skipped),
        symbol_count=len(all_symbols),
        reference_count=len(all_references),
        import_count=len(all_imports),
    )

    with connect() as conn:
        clear_repo_index(conn, repo_key)
        insert_symbols(conn, repo_key, all_symbols)
        insert_references(conn, repo_key, all_references)
        insert_imports(conn, repo_key, all_imports)
        save_index_meta(conn, meta)
        conn.commit()

    return BuildResult(
        ok=True,
        repo_key=repo_key,
        meta=meta,
        skipped_files=skipped or None,
    )
