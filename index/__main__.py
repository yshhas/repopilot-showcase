"""CLI entry: python -m index.build"""

from __future__ import annotations

import argparse
import sys

from index.builder import build_index
from index.store import IndexDisabledError, is_index_enabled


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build RepoPilot repo index")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even when head_commit matches stored meta",
    )
    args = parser.parse_args(argv)

    if not is_index_enabled():
        print("Repo index is disabled (INDEX_ENABLED=0)", file=sys.stderr)
        return 1

    try:
        result = build_index(force=args.force)
    except IndexDisabledError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not result.ok:
        print(result.error or "Index build failed", file=sys.stderr)
        return 1

    meta = result.meta
    if meta is None:
        print("Index build produced no metadata", file=sys.stderr)
        return 1

    print("Repo index build complete")
    print("repo_key:", meta.repo_key[:16] + "...")
    print("head_commit:", meta.head_commit or "(none)")
    print("index_version:", meta.index_version)
    print("built_at:", meta.built_at)
    print(
        "counts:",
        "files=" + str(meta.file_count),
        "symbols=" + str(meta.symbol_count),
        "references=" + str(meta.reference_count),
        "imports=" + str(meta.import_count),
    )

    if result.skipped_files:
        print("skipped_files:", len(result.skipped_files))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
