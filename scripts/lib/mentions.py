"""Deterministic brand-mention detection in AI-assistant answers.

Ported from the approach in the open-source Lettertrace project (MIT), which
is also what Letterstory's phantom dashboards run on. The rules that matter:

* Terms are the brand name plus explicit aliases — **never a domain label**.
  Deriving "you" from you.com or "monday" from monday.com produces a ~100%
  mention rate off ordinary prose. An inflated rate is the failure this
  module exists to prevent; a missed spelling shows up as a zero somebody
  investigates. Given a choice of error, take the visible one.
* Word boundaries are custom `(?<![A-Za-z0-9])…(?![A-Za-z0-9])` lookarounds,
  not `\\b`, so a term containing punctuation ("Notion.so") still matches.
* Longest alias first, so "Open Hands" wins over "Open".
* Markdown link **labels** count as prose (a brand that is always rendered as
  a ranked-list link is still being named) unless the label itself reads as
  an address; bare URLs and link targets are blanked. A citation is not a
  mention — the two are tracked as separate currencies.
* Blanking is length-preserving so `first_position` offsets stay valid.

Known, accepted limit: a brand whose name is an ordinary English word
("Zoom") will match that word in prose. Aliases cannot save it; say so in
reports rather than silently over-counting.
"""

from __future__ import annotations

import re
from typing import Optional

_ADDRESS_RE = re.compile(r"^(?:https?://|www\.)|^[\w-]+(?:\.[\w-]+)+(?:/\S*)?$", re.IGNORECASE)
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
_BARE_URL_RE = re.compile(r"\bhttps?://[^\s<>\"')\]]+|\bwww\.[^\s<>\"')\]]+", re.IGNORECASE)


def brand_terms(name: str, aliases: Optional[list[str]] = None) -> list[str]:
    """Brand name plus aliases. Domains are deliberately NOT derived."""
    return [t for t in [name, *(aliases or [])] if t and t.strip()]


def build_regex(terms: list[str]) -> Optional[re.Pattern]:
    cleaned = sorted(
        {t.strip() for t in terms if len(t.strip()) >= 2},
        key=len, reverse=True,
    )
    if not cleaned:
        return None
    pattern = "(?<![A-Za-z0-9])(?:" + "|".join(re.escape(t) for t in cleaned) + ")(?![A-Za-z0-9])"
    return re.compile(pattern, re.IGNORECASE)


def _blank(match_text: str) -> str:
    return " " * len(match_text)


def strip_link_surfaces(text: str) -> str:
    """Remove URL surfaces (length-preserving): markdown link targets, bare
    URLs, www hosts. Markdown labels are kept unless they are addresses."""

    def md_sub(m: re.Match) -> str:
        label, target = m.group(1), m.group(2)
        if not label.strip() or _ADDRESS_RE.match(label.strip()):
            return _blank(m.group(0))
        return " " + label + " " + _blank("(" + target + ")")

    text = _MD_LINK_RE.sub(md_sub, text)
    return _BARE_URL_RE.sub(lambda m: _blank(m.group(0)), text)


def detect_mention(text: str, terms: list[str]) -> dict:
    """{mentioned, count, first_position}; first_position is the offset of
    the first hit divided by text length (0 = opening words), -1 if absent."""
    absent = {"mentioned": False, "count": 0, "first_position": -1.0}
    if not text:
        return absent
    regex = build_regex(terms)
    if regex is None:
        return absent
    surface = strip_link_surfaces(text)
    matches = list(regex.finditer(surface))
    if not matches:
        return absent
    length = max(len(surface), 1)
    return {
        "mentioned": True,
        "count": len(matches),
        "first_position": min(matches[0].start() / length, 1.0),
    }


def detect_entities(text: str, entities: dict[str, list[str]]) -> dict[str, dict]:
    """Run detect_mention for several entities at once: {key: terms} in,
    {key: hit} out. Keys are caller-defined (e.g. "brand", competitor ids)."""
    return {key: detect_mention(text, terms) for key, terms in entities.items()}
