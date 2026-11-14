"""SQLite persistence for repo index."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import config.settings as settings
from index.models import ImportRecord, IndexMeta, ReferenceRecord, SymbolRecord


class IndexDisabledError(RuntimeError):
    pass


_SCHEMA = """
CREATE TABLE IF NOT EXISTS index_meta (
    repo_key TEXT PRIMARY KEY,
    head_commit TEXT,
    index_version INTEGER NOT NULL,
    built_at TEXT NOT NULL,
    file_count INTEGER NOT NULL,
    symbol_count INTEGER NOT NULL,
    reference_count INTEGER NOT NULL,
    import_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY,
    repo_key TEXT NOT NULL,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    lineno INTEGER NOT NULL,
    end_lineno INTEGER,
    qualname TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_symbols_repo_name
    ON symbols(repo_key, name);
CREATE INDEX IF NOT EXISTS idx_symbols_repo_path
    ON symbols(repo_key, path);

CREATE TABLE IF NOT EXISTS symbol_references (
    id INTEGER PRIMARY KEY,
    repo_key TEXT NOT NULL,
    symbol_name TEXT NOT NULL,
    path TEXT NOT NULL,
    lineno INTEGER NOT NULL,
    col_offset INTEGER,
    context TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_symbol_references_repo_name
    ON symbol_references(repo_key, symbol_name);

CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY,
    repo_key TEXT NOT NULL,
    path TEXT NOT NULL,
    imported_module TEXT NOT NULL,
    imported_name TEXT,
    lineno INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_imports_repo_path
    ON imports(repo_key, path);
"""


def is_index_enabled() -> bool:
    return bool(settings.INDEX_ENABLED)


def index_db_path() -> Path:
    return Path(settings.INDEX_DB_FILE)


def ensure_enabled() -> None:
    if not is_index_enabled():
        raise IndexDisabledError("Repo index is disabled (INDEX_ENABLED=0)")


def connect() -> sqlite3.Connection:
    ensure_enabled()
    db_path = index_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


def clear_repo_index(conn: sqlite3.Connection, repo_key: str) -> None:
    for table in ("symbols", "symbol_references", "imports", "index_meta"):
        conn.execute(f"DELETE FROM {table} WHERE repo_key = ?", (repo_key,))


def save_index_meta(conn: sqlite3.Connection, meta: IndexMeta) -> None:
    conn.execute(
        """
        INSERT INTO index_meta (
            repo_key, head_commit, index_version, built_at,
            file_count, symbol_count, reference_count, import_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(repo_key) DO UPDATE SET
            head_commit = excluded.head_commit,
            index_version = excluded.index_version,
            built_at = excluded.built_at,
            file_count = excluded.file_count,
            symbol_count = excluded.symbol_count,
            reference_count = excluded.reference_count,
            import_count = excluded.import_count
        """,
        (
            meta.repo_key,
            meta.head_commit,
            meta.index_version,
            meta.built_at,
            meta.file_count,
            meta.symbol_count,
            meta.reference_count,
            meta.import_count,
        ),
    )


def load_index_meta(conn: sqlite3.Connection, repo_key: str) -> IndexMeta | None:
    row = conn.execute(
        "SELECT * FROM index_meta WHERE repo_key = ?",
        (repo_key,),
    ).fetchone()
    if row is None:
        return None
    return IndexMeta(
        repo_key=row["repo_key"],
        head_commit=row["head_commit"],
        index_version=row["index_version"],
        built_at=row["built_at"],
        file_count=row["file_count"],
        symbol_count=row["symbol_count"],
        reference_count=row["reference_count"],
        import_count=row["import_count"],
    )


def insert_symbols(
    conn: sqlite3.Connection,
    repo_key: str,
    symbols: list[SymbolRecord],
) -> None:
    conn.executemany(
        """
        INSERT INTO symbols (
            repo_key, path, name, kind, lineno, end_lineno, qualname
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                repo_key,
                item.path,
                item.name,
                item.kind,
                item.lineno,
                item.end_lineno,
                item.qualname,
            )
            for item in symbols
        ],
    )


def insert_references(
    conn: sqlite3.Connection,
    repo_key: str,
    references: list[ReferenceRecord],
) -> None:
    conn.executemany(
        """
        INSERT INTO symbol_references (
            repo_key, symbol_name, path, lineno, col_offset, context
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                repo_key,
                item.symbol_name,
                item.path,
                item.lineno,
                item.col_offset,
                item.context,
            )
            for item in references
        ],
    )


def insert_imports(
    conn: sqlite3.Connection,
    repo_key: str,
    imports: list[ImportRecord],
) -> None:
    conn.executemany(
        """
        INSERT INTO imports (
            repo_key, path, imported_module, imported_name, lineno
        ) VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                repo_key,
                item.path,
                item.imported_module,
                item.imported_name,
                item.lineno,
            )
            for item in imports
        ],
    )


def fetch_symbol_definitions(
    conn: sqlite3.Connection,
    repo_key: str,
    name: str,
    *,
    limit: int,
) -> list[SymbolRecord]:
    rows = conn.execute(
        """
        SELECT path, name, kind, lineno, end_lineno, qualname
        FROM symbols
        WHERE repo_key = ? AND name = ?
        ORDER BY path, lineno
        LIMIT ?
        """,
        (repo_key, name, limit),
    ).fetchall()
    return [
        SymbolRecord(
            path=row["path"],
            name=row["name"],
            kind=row["kind"],
            lineno=row["lineno"],
            end_lineno=row["end_lineno"],
            qualname=row["qualname"],
        )
        for row in rows
    ]


def fetch_symbol_references(
    conn: sqlite3.Connection,
    repo_key: str,
    name: str,
    *,
    limit: int,
) -> list[ReferenceRecord]:
    rows = conn.execute(
        """
        SELECT path, symbol_name, lineno, col_offset, context
        FROM symbol_references
        WHERE repo_key = ? AND symbol_name = ?
        ORDER BY path, lineno
        LIMIT ?
        """,
        (repo_key, name, limit),
    ).fetchall()
    return [
        ReferenceRecord(
            path=row["path"],
            symbol_name=row["symbol_name"],
            lineno=row["lineno"],
            col_offset=row["col_offset"],
            context=row["context"],
        )
        for row in rows
    ]


def fetch_file_imports(
    conn: sqlite3.Connection,
    repo_key: str,
    path: str,
    *,
    limit: int,
) -> list[ImportRecord]:
    rows = conn.execute(
        """
        SELECT path, imported_module, imported_name, lineno
        FROM imports
        WHERE repo_key = ? AND path = ?
        ORDER BY lineno
        LIMIT ?
        """,
        (repo_key, path, limit),
    ).fetchall()
    return [
        ImportRecord(
            path=row["path"],
            imported_module=row["imported_module"],
            imported_name=row["imported_name"],
            lineno=row["lineno"],
        )
        for row in rows
    ]
