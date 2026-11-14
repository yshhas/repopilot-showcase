"""CLI entry: python -m rag.build"""

from __future__ import annotations

import argparse
import sys

from rag.builder import build_rag_index
from rag.store import RagDisabledError, is_rag_enabled


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build RepoPilot repo RAG index")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even when head_commit matches stored meta",
    )
    args = parser.parse_args(argv)

    if not is_rag_enabled():
        print("Repo RAG is disabled (RAG_ENABLED=0)", file=sys.stderr)
        return 1

    try:
        result = build_rag_index(force=args.force)
    except RagDisabledError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not result.ok:
        print(result.error or "RAG build failed", file=sys.stderr)
        return 1

    meta = result.meta
    if meta is None:
        print("RAG build produced no metadata", file=sys.stderr)
        return 1

    print("Repo RAG build complete")
    print("repo_key:", meta.repo_key[:16] + "...")
    print("head_commit:", meta.head_commit or "(none)")
    print("rag_version:", meta.rag_version)
    print("built_at:", meta.built_at)
    print(
        "counts:",
        "files=" + str(meta.file_count),
        "chunks=" + str(meta.chunk_count),
    )
    print("embedding_model:", meta.embedding_model)
    print("embedding_dim:", meta.embedding_dim)

    if result.skipped_files:
        print("skipped_files:", len(result.skipped_files))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
