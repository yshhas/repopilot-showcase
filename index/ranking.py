"""File ranking and context budget selection (v0.6 C2)."""

from __future__ import annotations

from dataclasses import dataclass, field

import config.settings as settings
from index.models import IndexHit
from index.protocol import RetrievalHit


@dataclass
class FileCandidate:
    path: str
    score: float
    sources: list[str] = field(default_factory=list)
    reason: str = ""


def _normalize_path(path: str) -> str:
    return str(path).strip().replace("\\", "/")


def add_candidate(
    bucket: dict[str, FileCandidate],
    path: str,
    score: float,
    source: str,
    reason: str = "",
) -> None:
    normalized = _normalize_path(path)
    if not normalized:
        return

    existing = bucket.get(normalized)
    if existing is None:
        bucket[normalized] = FileCandidate(
            path=normalized,
            score=score,
            sources=[source],
            reason=reason or source,
        )
        return

    existing.score += score
    if source not in existing.sources:
        existing.sources.append(source)
    if reason:
        existing.reason = "+".join(existing.sources) + "; " + reason
    else:
        existing.reason = "+".join(existing.sources)


def candidates_from_paths(
    paths: list[str],
    *,
    source: str,
    score: float,
) -> list[FileCandidate]:
    bucket: dict[str, FileCandidate] = {}
    for path in paths:
        add_candidate(bucket, path, score, source)
    return list(bucket.values())


def candidates_from_symbol_hits(hits: list[IndexHit]) -> list[FileCandidate]:
    bucket: dict[str, FileCandidate] = {}
    for hit in hits:
        weight = 90.0 if hit.entry_type == "definition" else 80.0
        add_candidate(
            bucket,
            hit.path,
            weight,
            "symbol_" + hit.entry_type,
            hit.entry_type + "@" + str(hit.lineno),
        )
    return list(bucket.values())


def candidates_from_dependency_lists(
    anchor_path: str,
    imports: list[str],
    dependents: list[str],
) -> list[FileCandidate]:
    bucket: dict[str, FileCandidate] = {}
    anchor = _normalize_path(anchor_path)

    if anchor:
        add_candidate(bucket, anchor, 95.0, "dependency_anchor", "anchor file")

    for item in imports:
        add_candidate(bucket, _import_to_path_guess(item), 55.0, "import_neighbor", "import of " + anchor)

    for item in dependents:
        add_candidate(bucket, item, 60.0, "dependent_neighbor", "dependent of " + anchor)

    return list(bucket.values())


def _import_to_path_guess(module_name: str) -> str:
    text = str(module_name).strip()
    if not text:
        return text
    return text.replace(".", "/") + ".py"


def candidates_from_retrieval_hits(hits: list[RetrievalHit]) -> list[FileCandidate]:
    bucket: dict[str, FileCandidate] = {}

    for hit in hits:
        if "semantic" not in hit.backend:
            continue

        weight = min(70.0, max(50.0, 50.0 + hit.score * 28.0))
        add_candidate(
            bucket,
            hit.path,
            weight,
            "semantic",
            "semantic@" + str(hit.line),
        )

    return list(bucket.values())


def rank_file_candidates(candidates: list[FileCandidate]) -> list[FileCandidate]:
    merged: dict[str, FileCandidate] = {}
    for item in candidates:
        add_candidate(
            merged,
            item.path,
            item.score,
            item.sources[0] if item.sources else "unknown",
            item.reason,
        )

    ranked = sorted(merged.values(), key=lambda c: (-c.score, c.path))
    return ranked[: settings.CONTEXT_RANK_MAX_FILES]


@dataclass
class ContextBudgetResult:
    selected: list[FileCandidate]
    truncated: list[FileCandidate]
    candidates_count: int
    selected_count: int
    truncated_count: int
    truncation_reason: str
    budget_chars: int
    chars_used: int
    rank_source: str


def apply_context_budget(
    ranked: list[FileCandidate],
    *,
    budget_chars: int | None = None,
    rank_source: str = "target_files",
    file_char_estimates: dict[str, int] | None = None,
) -> ContextBudgetResult:
    limit = budget_chars or settings.CONTEXT_BUDGET_CHARS
    estimates = file_char_estimates or {}

    rank_cap = settings.CONTEXT_RANK_MAX_FILES
    candidates_count = len(ranked)
    preselected = ranked[:rank_cap]
    rank_truncated = ranked[rank_cap:]

    selected: list[FileCandidate] = []
    truncated: list[FileCandidate] = list(rank_truncated)
    chars_used = 0
    truncation_reason = "none"

    for candidate in preselected:
        estimate = estimates.get(candidate.path, 4000)
        if chars_used + estimate > limit and selected:
            truncated.append(candidate)
            truncation_reason = "budget_exceeded"
            continue
        if chars_used + estimate > limit and not selected:
            selected.append(candidate)
            chars_used += min(estimate, limit)
            truncation_reason = "budget_exceeded"
            break

        selected.append(candidate)
        chars_used += estimate

    if rank_truncated and truncation_reason == "none":
        truncation_reason = "rank_cut"

    if truncated and truncation_reason == "none":
        truncation_reason = "budget_exceeded"

    return ContextBudgetResult(
        selected=selected,
        truncated=truncated,
        candidates_count=candidates_count,
        selected_count=len(selected),
        truncated_count=len(truncated),
        truncation_reason=truncation_reason,
        budget_chars=limit,
        chars_used=chars_used,
        rank_source=rank_source,
    )


def format_selection_summary(result: ContextBudgetResult) -> str:
    lines = [
        "===== 上下文选择摘要 =====",
        "候选文件: "
        + str(result.candidates_count)
        + " · 已加载: "
        + str(result.selected_count)
        + " · 已跳过: "
        + str(result.truncated_count),
        "跳过原因: " + result.truncation_reason,
        "rank_source: " + result.rank_source,
    ]

    if result.truncated:
        paths = ", ".join(item.path for item in result.truncated[:10])
        if len(result.truncated) > 10:
            paths += ", ... +" + str(len(result.truncated) - 10) + " more"
        lines.append("跳过路径: " + paths)

    return "\n".join(lines)
