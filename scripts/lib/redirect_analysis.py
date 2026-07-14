"""Honest redirect taxonomy over crawl snapshots (schema v2).

Shared by seo-redirects and seo-technical-audit so the two skills can never
disagree about what a "loop" is. The taxonomy exists because the previous
implementation had ~100% false-positive AND ~100% false-negative rates:
trailing-slash normalization made every ordinary `/foo -> /foo/` redirect a
critical "loop" (tripping launch blockers on healthy sites), while genuine
loops never reached the detector at all (requests raises TooManyRedirects,
so a followable chain is by definition not a loop).

Taxonomy:
  redirect_loop            error_type == "too_many_redirects", or a raw URL
                           literally repeats in the hop sequence. CRITICAL —
                           the destination is genuinely unreachable. This is
                           the only launch-blocker-eligible type.
  redirect_chain           >= 2 hops with at least one substantive hop.
                           medium at 2 hops, high at >= 3.
  canonicalization_chain   >= 2 hops, every hop merely normalizing
                           (http->https->www is one rule stack). LOW.
  normalizing_redirect     single hop to the same page identity (slash/www/
                           scheme/case). INFO, aggregated — normal hygiene,
                           never a finding to "fix".
  link_to_redirect         an internal link whose target answers with a
                           redirect — update the link to point at the final
                           URL. LOW (one finding per target, with referrers).

Loop/chain comparisons use RAW URLs (a normalizing redirect is precisely a
raw-vs-folded difference); identity grouping uses urlnorm.canonical_key.
"""

from __future__ import annotations

from typing import Any, Optional

from . import urlnorm


def hop_sequence(record: dict[str, Any]) -> list[str]:
    """Raw URL sequence of a record's redirect walk: each redirecting hop,
    then the final landing URL (when known)."""
    hops = [h.get("url", "") for h in record.get("redirect_chain") or []]
    final = record.get("final_url") or ""
    if final:
        hops.append(final)
    return [h for h in hops if h]


def is_normalizing_hop(src: str, dst: str) -> bool:
    """A hop that changes the URL's spelling but not its identity."""
    return src != dst and urlnorm.same_page(src, dst)


def _hop_pairs(record: dict[str, Any]) -> list[tuple[str, str]]:
    """(source, target) per hop of a record's redirect walk."""
    chain = record.get("redirect_chain") or []
    final = record.get("final_url") or ""
    sources = [h.get("url", "") for h in chain]
    targets = sources[1:] + [final]
    return [(s, t) for s, t in zip(sources, targets) if s and t]


def _pure_normalizing(record: dict[str, Any]) -> bool:
    """Every hop of this record's redirect walk is mere normalization."""
    pairs = _hop_pairs(record)
    return bool(pairs) and all(is_normalizing_hop(s, t) or s == t for s, t in pairs)


def classify_record(record: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Classify one crawl record's redirect behavior. None = no redirect."""
    url = record.get("url", "")

    if record.get("error_type") == "too_many_redirects":
        return {
            "type": "redirect_loop",
            "severity": "critical",
            "url": url,
            "hops": hop_sequence(record),
            "detail": (
                "Fetching this URL exceeded the redirect limit — a genuine "
                "redirect loop; the destination is unreachable for users and "
                "crawlers alike."
            ),
            "auto_fixable": False,
        }

    seq = hop_sequence(record)
    if len(seq) >= 2 and len(set(seq)) < len(seq):
        return {
            "type": "redirect_loop",
            "severity": "critical",
            "url": url,
            "hops": seq,
            "detail": "A URL repeats verbatim within this redirect walk.",
            "auto_fixable": False,
        }

    chain = record.get("redirect_chain") or []
    if not chain:
        return None

    all_normalizing = _pure_normalizing(record)

    if len(chain) == 1:
        if all_normalizing:
            return {
                "type": "normalizing_redirect",
                "severity": "info",
                "url": url,
                "hops": seq,
                "detail": (
                    "Single-hop redirect to the same page identity (slash/www/"
                    "scheme normalization) — ordinary canonicalization hygiene, "
                    "not a defect."
                ),
                "auto_fixable": False,
            }
        return None  # single substantive redirect: normal (moved page), not a finding

    if all_normalizing:
        return {
            "type": "canonicalization_chain",
            "severity": "low",
            "url": url,
            "hops": seq,
            "detail": (
                f"{len(chain)}-hop chain where every hop is pure normalization "
                "(e.g. http->https->www). Collapsing to a single hop saves a "
                "round trip, but nothing is broken."
            ),
            "auto_fixable": False,
        }

    return {
        "type": "redirect_chain",
        "severity": "high" if len(chain) >= 3 else "medium",
        "url": url,
        "hops": seq,
        "detail": (
            f"{len(chain)}-hop redirect chain — each extra hop dilutes signal "
            "and slows users/crawlers; point the first URL directly at the "
            "final destination."
        ),
        "auto_fixable": False,
    }


def classify_snapshot(pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify every record and cross-reference internal links against
    redirecting targets. Returns finding lists plus counts."""
    findings: dict[str, list[dict[str, Any]]] = {
        "redirect_loop": [], "redirect_chain": [],
        "canonicalization_chain": [], "normalizing_redirect": [],
        "link_to_redirect": [],
    }

    redirecting: dict[str, dict[str, Any]] = {}  # canonical_key -> record
    for rec in pages:
        result = classify_record(rec)
        if result is not None:
            findings[result["type"]].append(result)
        if rec.get("redirect_chain"):
            redirecting[urlnorm.canonical_key(rec.get("url", ""))] = rec

    # Internal links pointing at URLs that answer with a redirect.
    referrers: dict[str, list[str]] = {}
    for rec in pages:
        if rec.get("status") != 200:
            continue
        for link in rec.get("internal_links") or []:
            key = urlnorm.canonical_key(link)
            target = redirecting.get(key)
            if target is None:
                continue
            # A link to a pure-normalizing redirect (slash/www/scheme) is not
            # worth a finding — but a link to ANY substantive redirect is,
            # including the single-hop moved-page case (classify_record
            # returns None for that shape only because it isn't a chain/loop
            # defect; the link should still point at the final destination).
            if _pure_normalizing(target):
                continue
            referrers.setdefault(key, []).append(rec.get("url", ""))

    for key, refs in referrers.items():
        target = redirecting[key]
        findings["link_to_redirect"].append({
            "type": "link_to_redirect",
            "severity": "low",
            "url": target.get("url", ""),
            "final_url": target.get("final_url", ""),
            "referrers": sorted(set(refs))[:20],
            "referrer_count": len(set(refs)),
            "detail": (
                "Internal links point at a URL that answers with a redirect — "
                "update them to link the final destination directly."
            ),
            "auto_fixable": False,
        })

    return {
        "findings": findings,
        "counts": {k: len(v) for k, v in findings.items()},
    }


def new_redirect_regressions(
    previous_by_key: dict[str, dict[str, Any]],
    current_by_key: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Diff helper for seo-maintain: pages that answered directly (200, no
    hops) in the baseline but now answer with a redirect. High severity when
    the landing host differs (possible hijack-shaped change)."""
    regressions = []
    for key, cur in current_by_key.items():
        chain = cur.get("redirect_chain") or []
        if not chain:
            continue
        prev = previous_by_key.get(key)
        if prev is None or prev.get("status") != 200 or prev.get("redirect_chain"):
            continue
        cross_host = urlnorm.is_cross_host_canonical(
            cur.get("final_url", ""), cur.get("url", ""))
        regressions.append({
            "type": "new_redirect_on_previously_direct_page",
            "severity": "high" if cross_host else "medium",
            "url": cur.get("url", ""),
            "final_url": cur.get("final_url", ""),
            "hops": hop_sequence(cur),
            "detail": (
                "This page served 200 directly in the previous snapshot and "
                "now redirects"
                + (" to a DIFFERENT HOST — review immediately (hijack-shaped)."
                   if cross_host else
                   " — confirm the redirect is intentional (page move/retirement).")
            ),
            "human_review_required": True,
            "auto_fixable": False,
        })
    return regressions
