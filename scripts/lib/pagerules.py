"""Shared page-level predicates over crawl records.

Five scripts used to carry inline (and mutually inconsistent) noindex
checks — several looked only at the meta robots tag and ignored the
`X-Robots-Tag` response header the crawler also captures. These helpers are
the single implementation. They accept either a PageRecord dataclass or a
plain dict loaded from a JSONL snapshot.
"""

from __future__ import annotations

from typing import Any


def _get(rec: Any, field: str, default: Any = "") -> Any:
    if isinstance(rec, dict):
        return rec.get(field, default)
    return getattr(rec, field, default)


def _robots_directives(rec: Any) -> str:
    meta = str(_get(rec, "meta_robots") or "")
    header = str(_get(rec, "x_robots_tag") or "")
    return f"{meta},{header}".lower()


def is_noindex(rec: Any) -> bool:
    """True if the page opts out of indexing via the meta robots tag OR the
    X-Robots-Tag header. `none` means `noindex, nofollow` per Google."""
    directives = _robots_directives(rec)
    return "noindex" in directives or "none" in directives.split(",")


def is_nofollow_page(rec: Any) -> bool:
    """True if the page's robots directives forbid following its links."""
    directives = _robots_directives(rec)
    return "nofollow" in directives or "none" in directives.split(",")


def is_html(rec: Any) -> bool:
    content_type = str(_get(rec, "content_type") or "").lower()
    return "text/html" in content_type or "application/xhtml+xml" in content_type


def is_indexable_html(rec: Any) -> bool:
    """A successfully-fetched HTML page that is eligible for indexing."""
    if _get(rec, "error"):
        return False
    return int(_get(rec, "status") or 0) == 200 and is_html(rec) and not is_noindex(rec)
