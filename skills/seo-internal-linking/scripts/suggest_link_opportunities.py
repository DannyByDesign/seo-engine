"""seo-internal-linking: suggest contextual link-insertion opportunities.

Takes a flagged page (orphan/unreachable/deep, as reported by
analyze_link_graph.py) plus the other pages of the same crawl snapshot, and
uses simple keyword/entity overlap matching (title, H1s, H2s, OG tags -- no
external NLP dependency, no LLM call) to suggest WHICH other existing pages
are topically related enough that a contextual link to the target page could
plausibly be inserted into an existing paragraph there.

Snapshots come from the shared store (scripts.lib.snapshots); this script
never crawls on its own -- run analyze_link_graph.py first. Page identity is
urlnorm.canonical_key of the FINAL destination URL, so a page can never be
suggested as a link candidate for itself via a slash/www/redirect alias, and
duplicate crawl records of one page are folded before scoring. Candidates
and targets are both restricted to indexable pages
(scripts.lib.pagerules.is_indexable_html): a suggestion never proposes
linking FROM a noindex page (its links don't confer discoverability the way
this skill intends) or TO a noindex page (which has opted out of indexing).

This deliberately does NOT:
  - fetch/parse full page HTML to locate a specific existing sentence to
    edit (the crawl snapshot only carries title/h1/h2/word_count/content_hash
    signals, not full body text) -- it identifies CANDIDATE pages and the
    shared terms that justify the connection, and leaves finding/editing the
    actual sentence to the calling agent, which should open the real source
    file for the candidate page and read it in context.
  - rank candidates by anything other than topical overlap -- no attempt to
    predict which insertion would move rankings the most. That would be
    optimizing for a ranking signal directly rather than for genuine
    relevance, which is the thing seo-playbook.md §6 says NOT to do
    ("this is a durable strategy... because it mirrors how a genuinely
    comprehensive resource on a topic would naturally link itself").
  - ever auto-insert a link. Every suggestion here is a candidate for human/
    agent review of whether the anchor context genuinely fits -- per
    red-flags.md, careless automated anchor-text insertion reads as
    manipulative link building, not genuine editorial linking.

Usage:
    python3 suggest_link_opportunities.py --target-url https://example.com/orphan-page
    python3 suggest_link_opportunities.py --from-analysis   # process every
        orphan_page/unreachable_page/deep_page finding from the most recent
        analyze_link_graph.py run in one batch
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional


if sys.version_info < (3, 9):
    sys.exit("seo-engine requires Python 3.9+ (found %d.%d)" % sys.version_info[:2])


def _find_engine_root(start: Path) -> Path:
    import os

    env = os.environ.get("SEO_ENGINE_ROOT")
    if env and (Path(env) / "scripts" / "lib" / "config.py").is_file():
        return Path(env)
    for candidate in [start, *start.parents]:
        if (candidate / "scripts" / "lib" / "config.py").is_file():
            return candidate
    raise SystemExit(
        "Could not locate seo-engine root (scripts/lib/config.py). If skills were "
        "copied (not symlinked), set SEO_ENGINE_ROOT=/path/to/seo-engine."
    )


sys.path.insert(0, str(_find_engine_root(Path(__file__).resolve())))
from scripts.lib import config as config_module  # noqa: E402
from scripts.lib import pagerules, snapshots, urlnorm  # noqa: E402

DEFAULT_MAX_CANDIDATES = 5
DEFAULT_MIN_SCORE = 0.08  # below this, overlap is too thin to be a genuine signal
SNAPSHOT_MAX_AGE_HOURS = 24

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "have", "how", "in", "into", "is", "it", "its", "of", "on", "or", "our",
    "than", "that", "the", "their", "this", "to", "up", "vs", "was", "were",
    "will", "with", "your", "you", "we", "i", "us", "&", "-", "|", ":",
    "about", "all", "also", "can", "more", "not", "one", "out", "so", "if",
    "no", "do", "does", "get", "new", "use", "used", "using",
}

_WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def _tokenize(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall((text or "").lower()) if w not in STOPWORDS and len(w) > 2]


def _weighted_terms(page: dict[str, Any]) -> Counter:
    """Weight title/H1 terms higher than H2/OG terms -- a shared word in the
    page's own title/H1 is a much stronger topical signal than one that only
    appears in a subheading, per how a human would judge topical relatedness."""
    weighted: Counter = Counter()
    for term in _tokenize(page.get("title") or ""):
        weighted[term] += 3
    for term in _tokenize(" ".join(page.get("h1") or [])):
        weighted[term] += 3
    for term in _tokenize(" ".join(page.get("h2") or [])):
        weighted[term] += 1
    for term in _tokenize(" ".join((page.get("og") or {}).values())):
        weighted[term] += 1
    return weighted


def _overlap_score(target_terms: Counter, candidate_terms: Counter) -> tuple[float, list[str]]:
    """Cosine-like overlap over weighted term-frequency vectors, restricted to
    shared terms (a simple, dependency-free proxy for topical/entity overlap
    -- no embeddings, no external NLP library required per the "simple
    keyword/entity overlap matching" scope in this skill's assignment)."""
    shared = set(target_terms) & set(candidate_terms)
    if not shared:
        return 0.0, []

    numerator = sum(target_terms[t] * candidate_terms[t] for t in shared)
    target_norm = sum(v * v for v in target_terms.values()) ** 0.5
    candidate_norm = sum(v * v for v in candidate_terms.values()) ** 0.5
    if target_norm == 0 or candidate_norm == 0:
        return 0.0, []

    score = numerator / (target_norm * candidate_norm)
    shared_sorted = sorted(shared, key=lambda t: target_terms[t] * candidate_terms[t], reverse=True)
    return score, shared_sorted


def _index_indexable(pages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """canonical_key(final destination) -> record, indexable HTML pages only
    (pagerules.is_indexable_html — covers status, content type, and noindex
    via both the meta robots tag and the X-Robots-Tag header). Folding by the
    final destination means /about, /about/, and the www alias are ONE page."""
    by_key: dict[str, dict[str, Any]] = {}
    for rec in pages:
        if not pagerules.is_indexable_html(rec):
            continue
        key = urlnorm.canonical_key(rec.get("final_url") or rec.get("url", ""))
        if key and key not in by_key:
            by_key[key] = rec
    return by_key


def find_candidates(
    target_key: str,
    target_page: dict[str, Any],
    pages_by_key: dict[str, dict[str, Any]],
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    min_score: float = DEFAULT_MIN_SCORE,
) -> list[dict[str, Any]]:
    """Rank every other indexable page by weighted keyword/entity overlap
    with the target page. Returns candidates above min_score, highest-scoring
    first. Candidates whose folded identity equals the target's are excluded
    -- a page must never be proposed as a link source for itself via a
    trailing-slash/www/redirect alias."""
    target_terms = _weighted_terms(target_page)
    if not target_terms:
        return []

    scored = []
    for key, page in pages_by_key.items():
        if key == target_key:
            continue
        # Note: this function does not itself filter out candidate pages that
        # are orphaned/unreachable -- a link inserted on a page nobody can
        # find doesn't help discovery. That check is deliberately left to the
        # human/agent review step (see human_review_checklist in
        # build_suggestion(), item 4: cross-check analyze_link_graph.py's
        # link_graph_depths for the candidate URL) rather than silently
        # filtered here, since this script does not require analyze_link_graph.py's
        # output to run in --target-url mode.
        candidate_terms = _weighted_terms(page)
        score, shared_terms = _overlap_score(target_terms, candidate_terms)
        if score >= min_score:
            scored.append({
                "candidate_url": page.get("final_url") or page.get("url", ""),
                "candidate_title": page.get("title", ""),
                "overlap_score": round(score, 4),
                "shared_terms": shared_terms[:12],
                "candidate_word_count": page.get("word_count", 0),
                "candidate_h2": page.get("h2", [])[:8],
            })

    scored.sort(key=lambda c: c["overlap_score"], reverse=True)
    return scored[:max_candidates]


def build_suggestion(
    target_page: dict[str, Any],
    candidates: list[dict[str, Any]],
    finding_type: Optional[str] = None,
) -> dict[str, Any]:
    target_url = target_page.get("final_url") or target_page.get("url", "")
    if not candidates:
        return {
            "target_url": target_url,
            "target_title": target_page.get("title", ""),
            "finding_type": finding_type,
            "candidate_count": 0,
            "candidates": [],
            "detail": (
                f"No other crawled page shares enough title/heading vocabulary with "
                f"{target_url} to suggest a confident contextual-link candidate "
                "(overlap below the minimum threshold on every other page). This "
                "may mean the page covers a genuinely standalone topic -- consider "
                "whether it needs a new hub/cluster page, or whether related content "
                "exists but simply isn't titled/headed in overlapping language yet."
            ),
            "auto_apply": False,
        }

    return {
        "target_url": target_url,
        "target_title": target_page.get("title", ""),
        "finding_type": finding_type,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "detail": (
            f"{len(candidates)} existing page(s) share enough topical vocabulary with "
            f"{target_url} to be plausible homes for a contextual link. For each "
            "candidate, open its actual source content and look for an existing "
            "paragraph discussing the shared terms below -- insert a descriptive, "
            "non-generic anchor-text link to the target page there ONLY if it reads "
            "as something the page's author would naturally have written, not as an "
            "inserted reference."
        ),
        "auto_apply": False,
        "human_review_checklist": [
            "Open the candidate page's actual source content (not just the crawl "
            "snapshot's title/H1/H2 signals used to rank it here).",
            "Confirm an existing sentence or paragraph genuinely discusses the "
            "shared topic/terms -- do not insert a new sentence solely to host a "
            "link, and do not append a generic 'Related: [link]' block.",
            "Write descriptive anchor text naming the destination's actual "
            "subject (per seo-playbook.md §6: anchor text should describe the "
            "destination, not \"click here\").",
            "Confirm the candidate page itself is reachable from the homepage "
            "(check analyze_link_graph.py's output) -- a link added to another "
            "orphan/unreachable page does not fix discoverability.",
            "If no genuinely fitting sentence exists on any candidate, do not "
            "force one in -- report back that no natural insertion point was "
            "found rather than fabricating context.",
        ],
    }


def _skipped_suggestion(url: str, finding_type: Optional[str], reason: str) -> dict[str, Any]:
    return {
        "target_url": url,
        "target_title": "",
        "finding_type": finding_type,
        "candidate_count": 0,
        "candidates": [],
        "skipped": True,
        "skipped_reason": reason,
        "auto_apply": False,
    }


def _resolve_snapshot(cfg: config_module.Config,
                      report_snapshot_path: Optional[str]) -> Optional[snapshots.Snapshot]:
    """Prefer the exact snapshot the analysis report was built from (so
    suggestions and findings share one crawl); fall back to the newest
    reusable snapshot in the store."""
    if report_snapshot_path:
        for snap in snapshots.all_snapshots(cfg, site_url=cfg.site_url):
            if str(snap.path) == report_snapshot_path:
                return snap
    return snapshots.latest(cfg, max_age_hours=SNAPSHOT_MAX_AGE_HOURS)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="seo-internal-linking: suggest existing pages where a "
                    "contextual link to a flagged (orphan/unreachable/deep) page "
                    "could naturally be added."
    )
    parser.add_argument("--target-url", default=None,
                        help="the flagged page URL to find link-insertion "
                            "candidates for (must exist in the crawl snapshot)")
    parser.add_argument("--from-analysis", action="store_true",
                        help="batch mode: process every orphan_page/unreachable_page/"
                            "deep_page finding from the most recent "
                            "analyze_link_graph.py report in .seo-engine/reports/")
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES,
                        help=f"max candidate pages to suggest per target (default {DEFAULT_MAX_CANDIDATES})")
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE,
                        help=f"minimum overlap score to surface a candidate (default {DEFAULT_MIN_SCORE})")
    args = parser.parse_args()

    cfg = config_module.load()

    if not args.target_url and not args.from_analysis:
        json.dump({
            "error": "Provide --target-url <url> or --from-analysis (batch mode).",
        }, sys.stdout, indent=2)
        print()
        sys.exit(1)

    analysis_report: Optional[dict[str, Any]] = None
    if args.from_analysis:
        dated_reports = sorted(cfg.reports_dir.glob("internal-linking-*.json"), reverse=True)
        if not dated_reports:
            json.dump({
                "error": (
                    "--from-analysis requires a prior analyze_link_graph.py run "
                    f"(no internal-linking-*.json report found in {cfg.reports_dir}). "
                    "Run analyze_link_graph.py first."
                ),
            }, sys.stdout, indent=2)
            print()
            sys.exit(1)
        analysis_report = json.loads(dated_reports[0].read_text(encoding="utf-8"))

    snap = _resolve_snapshot(
        cfg, analysis_report.get("snapshot_path") if analysis_report else None)
    if snap is None:
        json.dump({
            "error": (
                "No reusable crawl snapshot found in the shared store "
                "(.seo-engine/state/crawls/). This script never crawls on its "
                "own — run analyze_link_graph.py first (it crawls and stores a "
                "snapshot), then re-run this script."
            ),
        }, sys.stdout, indent=2)
        print()
        sys.exit(1)

    pages = list(snap.pages())
    pages_by_key = _index_indexable(pages)
    alias_map = urlnorm.build_alias_map(pages)

    def lookup(url: str) -> tuple[str, Optional[dict[str, Any]]]:
        key = urlnorm.resolve_alias(urlnorm.canonical_key(url), alias_map)
        return key, pages_by_key.get(key)

    targets: list[tuple[str, str, Optional[dict[str, Any]], Optional[str]]] = []

    if args.target_url:
        key, target_page = lookup(args.target_url)
        if target_page is None:
            # Distinguish "not crawled" from "crawled but not indexable
            # (e.g. noindex)" so the caller gets an honest reason.
            crawled = any(
                urlnorm.resolve_alias(
                    urlnorm.canonical_key(r.get("final_url") or r.get("url", "")),
                    alias_map) == key
                for r in pages
            )
            if crawled:
                targets.append((args.target_url, key, None, None))
            else:
                json.dump({
                    "error": (
                        f"--target-url {args.target_url!r} was not found in the crawl "
                        f"snapshot at {snap.path}. It must be a URL from the same "
                        "crawl analyze_link_graph.py used."
                    ),
                }, sys.stdout, indent=2)
                print()
                sys.exit(1)
        else:
            targets.append((args.target_url, key, target_page, None))

    if args.from_analysis and analysis_report is not None:
        for finding in analysis_report.get("findings", []):
            if finding.get("type") not in ("orphan_page", "unreachable_page", "deep_page"):
                continue
            key, target_page = lookup(finding["url"])
            targets.append((finding["url"], key, target_page, finding.get("type")))

    suggestions = []
    skipped_noindex = 0
    for raw_url, key, target_page, finding_type in targets:
        if target_page is None:
            # In the snapshot's non-indexable set (noindex/non-200) or absent
            # from the crawl (e.g. an orphan_candidate that was never fetched).
            skipped_noindex += 1
            suggestions.append(_skipped_suggestion(
                raw_url, finding_type,
                "target is not an indexable crawled page (noindex — via meta "
                "robots or X-Robots-Tag — non-200, or never crawled); this "
                "skill never proposes internal links to pages that have opted "
                "out of indexing or whose indexability is unverified."))
            continue
        candidates = find_candidates(
            key, target_page, pages_by_key,
            max_candidates=args.max_candidates,
            min_score=args.min_score,
        )
        suggestions.append(build_suggestion(target_page, candidates, finding_type))

    output = {
        "site_url": cfg.site_url,
        "snapshot_path": str(snap.path),
        "mode": "from_analysis" if args.from_analysis else "single_target",
        "targets_processed": len(suggestions),
        "targets_with_candidates": sum(
            1 for s in suggestions if s["candidate_count"] > 0),
        "targets_with_no_candidates": sum(
            1 for s in suggestions
            if s["candidate_count"] == 0 and not s.get("skipped")),
        "targets_skipped": skipped_noindex,
        "suggestions": suggestions,
        "note": (
            "Every suggestion here is a candidate for human/agent review, never an "
            "auto-apply action. Per references/red-flags.md, automated anchor-text "
            "insertion done carelessly reads as manipulative link-building -- a human "
            "or code-aware agent must confirm the suggested anchor context genuinely "
            "fits the candidate page's existing content before inserting anything. "
            "See SKILL.md for the full review checklist."
        ),
    }

    snapshots.prune(cfg)

    json.dump(output, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
