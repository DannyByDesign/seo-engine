"""Markdown article operations shared by pub-write, pub-enhance and pub-publish:
block splitting, sentence splitting, number/link extraction, numeric-anchor
insertion, internal-link insertion, client-link stripping, and the
"nothing lost" guard used after any LLM rewrite.

All functions are pure and work on the markdown body (not the frontmatter).
"""

from __future__ import annotations

import re
from typing import Optional

_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+|/[^)\s]*)\)")
_NUMBER_RE = re.compile(
    r"(?<![\w/])(\$?\d[\d,]*(?:\.\d+)?\s?(?:%|percent|billion|million|thousand|bn|m\b|k\b|x\b)?)", re.I)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“(\[$0-9])")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


# ---------- blocks ----------

def blocks(md: str) -> list[dict]:
    """Split markdown into blocks: {kind: heading|para|list|code|quote|image|html|blank, text}."""
    out: list[dict] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append({"kind": "code", "text": "\n".join(lines[i:min(j + 1, len(lines))])})
            i = j + 1
            continue
        if not line.strip():
            out.append({"kind": "blank", "text": ""})
            i += 1
            continue
        if _HEADING_RE.match(line):
            out.append({"kind": "heading", "text": line})
            i += 1
            continue
        if re.match(r"^!\[[^\]]*\]\([^)]*\)\s*$", line.strip()):
            out.append({"kind": "image", "text": line})
            i += 1
            continue
        kind = "list" if re.match(r"^\s*(?:[-*+]|\d+\.)\s+", line) else "quote" if line.startswith(">") else "html" if line.lstrip().startswith("<") else "para"
        j = i
        while j + 1 < len(lines) and lines[j + 1].strip() and not _HEADING_RE.match(lines[j + 1]) and not lines[j + 1].startswith("```"):
            j += 1
        out.append({"kind": kind, "text": "\n".join(lines[i:j + 1])})
        i = j + 1
    return out


def join_blocks(items: list[dict]) -> str:
    text = "\n".join(b["text"] for b in items)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def headings(md: str, level: int = 2) -> list[str]:
    return [m.group(2).strip() for m in (_HEADING_RE.match(l) for l in md.splitlines()) if m and len(m.group(1)) == level]


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENT_SPLIT_RE.split(text.strip()) if s]


def word_count(md: str) -> int:
    text = _LINK_RE.sub(r"\1", md)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"[#>*_`|-]+", " ", text)
    return len(text.split())


# ---------- numbers & links ----------

def numbers_in(text: str) -> set[str]:
    """Normalized numeric tokens ('$2.08 billion' -> '2.08', '13.6%' -> '13.6%')."""
    out: set[str] = set()
    for m in _NUMBER_RE.finditer(text or ""):
        raw = m.group(1).lower().replace(",", "").replace("$", "").strip()
        num = re.match(r"\d+(?:\.\d+)?", raw)
        if not num:
            continue
        token = num.group(0)
        if re.search(r"%|percent", raw):
            token += "%"
        if len(token.rstrip("%")) <= 1 and not token.endswith("%"):
            continue  # skip bare single digits (list numbering, "one of 3")
        out.add(token)
    return out


def links_in(md: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in _LINK_RE.finditer(md or "")]


def _in_link(text: str, start: int, end: int) -> bool:
    for m in _LINK_RE.finditer(text):
        if m.start() <= start and end <= m.end():
            return True
    return False


_STAT_RE = re.compile(
    r"\$?\d[\d,]*(?:\.\d+)?\s*(?:%|percent|billion|million|thousand|bn|m\b|k\b)?"
    r"(?:\s*(?:to|-|–|—)\s*\$?\d[\d,]*(?:\.\d+)?\s*(?:%|percent|billion|million|thousand|bn|m\b|k\b)?)?", re.I)
_YEAR_RE = re.compile(r"^(?:19|20)\d\d$")


def statistic_tokens(text: str) -> list[str]:
    """Figures worth anchoring to a source, longest first: money, percentages,
    unit-suffixed numbers and ranges ('$25 to $60'). Bare years and bare small
    integers ('in 2026', '12 min', '1 in 6') are not statistics."""
    out: list[str] = []
    for m in _STAT_RE.finditer(text or ""):
        tok = m.group(0).strip().rstrip(".,;:")
        bare = tok.replace("$", "").replace(",", "").strip()
        marked = "$" in tok or "%" in tok or re.search(r"[a-z]", tok, re.I) is not None
        if not marked and (_YEAR_RE.match(bare) or re.fullmatch(r"\d{1,3}", bare)):
            continue
        if tok and tok not in out:
            out.append(tok)
    return sorted(out, key=len, reverse=True)


def anchor_number(paragraph: str, number_text: str, url: str) -> tuple[str, bool]:
    """Link the first unlinked occurrence of `number_text` (as written, e.g.
    '$2.08 billion' or '13.6%') to url. Returns (paragraph, changed). Several
    different figures may point at the same source within one paragraph — the
    measured articles do exactly that."""
    if not number_text:
        return paragraph, False
    pattern = re.compile(re.escape(number_text.strip()), re.I)
    for m in pattern.finditer(paragraph):
        if _in_link(paragraph, m.start(), m.end()):
            continue
        return paragraph[:m.start()] + f"[{m.group(0)}]({url})" + paragraph[m.end():], True
    return paragraph, False


def find_anchor_phrase(paragraph: str, title: str, min_tokens: int = 2) -> Optional[str]:
    """Longest run of >= min_tokens consecutive title words that appears
    verbatim (case-insensitive) in the paragraph outside existing links."""
    words = [w for w in re.findall(r"[A-Za-z0-9'’-]+", title)]
    plain = _LINK_RE.sub(lambda m: " " * len(m.group(0)), paragraph)
    best: Optional[str] = None
    for i in range(len(words)):
        for j in range(len(words), i + min_tokens - 1, -1):
            phrase = " ".join(words[i:j])
            if len(phrase) < 6:
                continue
            m = re.search(r"(?<![\w-])" + re.escape(phrase) + r"(?![\w-])", plain, re.I)
            if m:
                candidate = paragraph[m.start():m.end()]
                if best is None or len(candidate) > len(best):
                    best = candidate
                break
    return best


def insert_link(paragraph: str, phrase: str, url: str) -> tuple[str, bool]:
    if not phrase or url in paragraph:
        return paragraph, False
    for m in re.finditer(re.escape(phrase), paragraph):
        if _in_link(paragraph, m.start(), m.end()):
            continue
        return paragraph[:m.start()] + f"[{m.group(0)}]({url})" + paragraph[m.end():], True
    return paragraph, False


def strip_links_to_host(md: str, host: str) -> tuple[str, int]:
    """Replace [text](https://host/...) with plain text. Returns (md, removed)."""
    host = host.lower().removeprefix("www.")
    removed = 0

    def sub(m: re.Match) -> str:
        nonlocal removed
        link_host = re.sub(r"^https?://(www\.)?", "", m.group(2)).split("/")[0].lower()
        if link_host == host or link_host.endswith("." + host):
            removed += 1
            return m.group(1)
        return m.group(0)

    return _LINK_RE.sub(sub, md), removed


def guard_unchanged(before: str, after: str) -> list[str]:
    """Violations a rewrite must not introduce: lost/added numbers, lost links,
    changed headings, length outside 0.7-1.4x."""
    problems = []
    nb, na = numbers_in(before), numbers_in(after)
    if nb - na:
        problems.append(f"numbers lost: {sorted(nb - na)[:8]}")
    if na - nb:
        problems.append(f"numbers added: {sorted(na - nb)[:8]}")
    lb, la = {u for _, u in links_in(before)}, {u for _, u in links_in(after)}
    if lb - la:
        problems.append(f"links lost: {sorted(lb - la)[:5]}")
    if headings(before) != headings(after):
        problems.append("headings changed")
    wb, wa = max(word_count(before), 1), word_count(after)
    if not 0.7 <= wa / wb <= 1.4:
        problems.append(f"length changed {wb}->{wa} words")
    return problems
