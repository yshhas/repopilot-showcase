"""Shared utility functions used across the codebase.

Avoids duplication of common helpers like text truncation and path formatting.
"""


def truncate_text(text, limit: int) -> str:
    """Truncate *text* to at most *limit* characters, appending '...[truncated]' when cut."""
    s = str(text) if not isinstance(text, str) else text
    if len(s) > limit:
        return s[:limit] + "...[truncated]"
    return s


def format_paths_summary(paths: list[str]) -> str:
    """Return a compact display string for a list of file paths.

    When there are more than 5 paths, only the first 5 are listed followed by
    a count of the remaining items.
    """
    if len(paths) <= 5:
        return ", ".join(paths)
    return ", ".join(paths[:5]) + ", ... +" + str(len(paths) - 5) + " more"
