#!/usr/bin/env python3
"""Fail if new files import legacy mutation modules outside the whitelist."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

LEGACY_IMPORT_PREFIXES = (
    "context.mutation_fsm",
    "context.execution_state",
)

WHITELIST_SUFFIXES = {
    "context/mutation_fsm.py",
    "context/execution_state.py",
    "context/project_context.py",
    "context/tms/adapter.py",
    "context/tms/advance.py",
    "context/tms/backup.py",
    "context/tms/guards.py",
    "context/tms/resume.py",
    "context/tms/checkpoint_hydrate.py",
    "tools/outcome_schema.py",
    "tools/change_proposal.py",
    "tools/tool_manager.py",
    "react_agent.py",
    "test_tms_adapter.py",
    "test_tms_parity.py",
    "test_tms_sync_integration.py",
    "test_tool_result_schema.py",
    "test_tool_outcome_schema.py",
    "test_advance_from_outcome.py",
    "test_checkpoint_migration.py",
    "test_task_scoped_backup.py",
    "test_tms_guards.py",
    "test_m5_regression.py",
    "test_m5_checkpoint_save.py",
    "test_mutation_fsm.py",
    "test_mutation_fsm_checkpoint.py",
    "test_execution_state_dedup.py",
    "test_execution_state_dedup_tool.py",
    "test_llm_golden.py",
    "test_react_cancel_checkpoint.py",
    "test_checkpoint_store.py",
    "storage/checkpoint_store.py",
    "api/agent_runner.py",
    "scripts/check_no_legacy_imports.py",
    "conftest.py",
}


def _rel(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _is_whitelisted(path: Path) -> bool:
    rel = _rel(path)
    return rel in WHITELIST_SUFFIXES


def _legacy_imports_in_file(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    hits: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if any(name == prefix or name.startswith(prefix + ".") for prefix in LEGACY_IMPORT_PREFIXES):
                    hits.append(f"import {name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and any(
                node.module == prefix or node.module.startswith(prefix + ".")
                for prefix in LEGACY_IMPORT_PREFIXES
            ):
                hits.append(f"from {node.module} import ...")

    return hits


def main() -> int:
    violations: list[str] = []

    for path in PROJECT_ROOT.rglob("*.py"):
        rel = _rel(path)
        if rel.startswith(".venv/") or "/.venv/" in rel:
            continue
        if rel.startswith("legacy/"):
            continue
        if _is_whitelisted(path):
            continue

        hits = _legacy_imports_in_file(path)
        for hit in hits:
            violations.append(f"{rel}: {hit}")

    if violations:
        print("Legacy import policy violations:")
        for item in sorted(violations):
            print("  -", item)
        print("\nSee docs/design/tms_legacy_import_policy.md")
        return 1

    print("Legacy import policy: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
