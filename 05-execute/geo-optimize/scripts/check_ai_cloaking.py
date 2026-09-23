"""geo-optimize: AI-crawler cloaking check.

references/red-flags.md §1 ("Cloaking") and §5 ("GEO-specific gotchas") both
state the same extension of a classic policy: serving materially different
content to AI crawlers than to human visitors/Googlebot is the same
violation as classic cloaking, just against a newer set of user agents. This
script checks for that -- it does NOT check whether AI crawlers are blocked
(see audit_ai_crawlers.py for that); it checks whether, when they ARE allowed
to fetch a page, they get served the same substantive content a human would.

Method (and its hard limits, stated up front):

* The human-browser UA is fetched TWICE per URL -- first and last, bracketing
  every spoofed-crawler fetch. The gap between those two human fetches is the
  page's *natural variance* (A/B tests, rotating content, timestamps). A
  crawler-UA divergence is only flagged when it exceeds
  max(0.15, 3 x natural_variance) against BOTH human fetches -- a page that
  differs 20% between two identical human requests must not produce a
  "cloaking" flag at a 16% crawler gap.
* METHODOLOGY LIMITATION (carried on every finding and on the report): this
  is UA-only spoofing from a non-vendor IP. Real AI crawlers fetch from
  published vendor IP ranges, and bot-management layers routinely treat a
  spoofed UA from an unknown IP differently from the real crawler. A clean
  result does NOT prove absence of cloaking, and a WAF challenge does NOT
  prove cloaking. Confirm what real crawlers actually receive via server
  logs (geo-monitor's grep_ai_crawler_logs.py).
* WAF/bot-management challenges (403/429/503 with challenge signatures) are
  classified as `bot_management_interference` (medium) -- interference with
  THIS probe, distinct from `status_code_mismatch` (high), which is reserved
  for a hard block (4xx/5xx with NO challenge markers while humans get 200).
* `content_diverges` is capped at severity medium: a word-count gap cannot
  establish intent, and this script never concludes "this site is cloaking"
  on its own. It never modifies anything.

Usage:
    python3 check_ai_cloaking.py --urls https://example.com/ https://example.com/pricing
    python3 check_ai_cloaking.py --sample-from-crawl --max-pages 20
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


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
from scripts.lib import http_util, pagerules, snapshots  # noqa: E402
from scripts.lib.config import MissingConfigError  # noqa: E402

from bs4 import BeautifulSoup  # noqa: E402

# Human-browser baseline UA. Fetched twice (first and last) to measure the
# page's natural variance -- the self-consistency baseline every crawler-UA
# comparison is judged against.
HUMAN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Real, documented crawler user-agent strings (geo-playbook.md §4 / vendor
# docs). Every one of these -- Googlebot included -- is a SPOOFED probe when
# sent by this script: we are not fetching from the vendor's IP ranges, so
# results carry the methodology limitation below.
PROBE_USER_AGENTS = {
    "Googlebot": (
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    ),
    "OAI-SearchBot": "OAI-SearchBot/1.0 (+https://openai.com/searchbot)",
    "ChatGPT-User": "ChatGPT-User/1.0 (+https://openai.com/bot)",
    "GPTBot": "GPTBot/1.0 (+https://openai.com/gptbot)",
    "Claude-SearchBot": "Claude-SearchBot/1.0 (+https://support.claude.com)",
    "Claude-User": "Claude-User/1.0 (+https://support.claude.com)",
    "ClaudeBot": "ClaudeBot/1.0 (+https://support.claude.com)",
    "PerplexityBot": "PerplexityBot/1.0 (+https://docs.perplexity.ai/docs/perplexitybot)",
}

# Base gap-ratio threshold. The effective per-URL threshold is
# max(BASE_GAP_RATIO_THRESHOLD, 3 * natural_variance) where natural_variance
# is the gap between the two human-UA fetches of the same URL.
BASE_GAP_RATIO_THRESHOLD = 0.15

# WAF/bot-management challenge classification: these statuses combined with
# any of the signatures below mean the probe was challenged, not cloaked.
CHALLENGE_STATUSES = {403, 429, 503}
CHALLENGE_HEADER_NAMES = ("cf-mitigated", "cf-ray")
CHALLENGE_BODY_MARKERS = (
    "just a moment", "attention required", "px-captcha", "incapsula",
    "datadome", "hcaptcha", "captcha",
)

# Hard-block statuses for status_code_mismatch (only meaningful when the
# human baseline got 200 and NO challenge signatures are present).
HARD_BLOCK_STATUSES = {401, 403, 404, 410, 451}

METHODOLOGY_LIMITATION = (
    "UA-only spoofing from a non-vendor IP: real AI crawlers fetch from "
    "published vendor IP ranges, and bot-management layers treat a spoofed "
    "UA from an unknown IP differently from the real crawler. A clean result "
    "does not prove absence of cloaking, and a challenge does not prove "
    "cloaking. Confirm what real crawlers receive via server logs "
    "(geo-monitor's grep_ai_crawler_logs.py) before drawing conclusions."
)


def _extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def _gap(words: int, base_words: int) -> float:
    return abs(words - base_words) / max(base_words, 1)


def fetch_variant(url: str, ua_label: str, ua_string: str) -> dict:
    import hashlib

    try:
        resp = http_util.get(url, headers={"User-Agent": ua_string}, min_interval=0.5)
    except http_util.HttpError as exc:
        return {"ua_label": ua_label, "error": str(exc)}  # pre-sanitized

    body = resp.text or ""
    text = _extract_text(body) if "text/html" in resp.headers.get("Content-Type", "") else ""

    # Challenge-signature detection (only meaningful on challenge statuses).
    signals: list[str] = []
    if resp.status_code in CHALLENGE_STATUSES:
        header_keys = {k.casefold() for k in resp.headers.keys()}
        for name in CHALLENGE_HEADER_NAMES:
            if name in header_keys:
                signals.append(f"header:{name}")
        lowered_body = body[:200_000].casefold()
        for marker in CHALLENGE_BODY_MARKERS:
            if marker in lowered_body:
                signals.append(f"body:{marker}")

    return {
        "ua_label": ua_label,
        "status": resp.status_code,
        "word_count": len(text.split()),
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        "waf_challenge": bool(signals),
        "challenge_signals": signals,
    }


def check_url(url: str) -> dict:
    # Fetch order matters: human first, all spoofed probes, human last --
    # the two human fetches bracket the probes so natural variance is
    # measured over the same time window the probes ran in.
    human_first = fetch_variant(url, "human_first", HUMAN_UA)
    probes = {
        label: fetch_variant(url, label, ua_string)
        for label, ua_string in PROBE_USER_AGENTS.items()
    }
    human_last = fetch_variant(url, "human_last", HUMAN_UA)

    variants = {"human_first": human_first, **probes, "human_last": human_last}
    result: dict = {"url": url, "variants": variants, "findings": []}

    for human in (human_first, human_last):
        if "error" in human:
            result["not_checked"] = (
                "human-browser baseline fetch failed -- no comparison is "
                "possible for this URL: " + human["error"]
            )
            return result
    if human_first["status"] != 200 or human_last["status"] != 200:
        result["not_checked"] = (
            f"human-browser baseline did not return 200 (got "
            f"{human_first['status']}/{human_last['status']}) -- cloaking "
            "comparisons require a healthy human baseline; check the URL itself"
        )
        return result

    natural_variance = _gap(human_last["word_count"], human_first["word_count"])
    if human_first["content_hash"] == human_last["content_hash"]:
        natural_variance = 0.0
    effective_threshold = max(BASE_GAP_RATIO_THRESHOLD, 3 * natural_variance)
    result["natural_variance"] = round(natural_variance, 3)
    result["effective_gap_threshold"] = round(effective_threshold, 3)

    for ai_label, probe in probes.items():
        if "error" in probe:
            continue

        if probe["status"] != 200:
            if probe["waf_challenge"]:
                result["findings"].append({
                    "url": url,
                    "ai_user_agent": ai_label,
                    "issue": "bot_management_interference",
                    "severity": "medium",
                    "ai_status": probe["status"],
                    "baseline_status": 200,
                    "challenge_signals": probe["challenge_signals"],
                    "detail": (
                        f"The spoofed {ai_label} User-Agent received HTTP "
                        f"{probe['status']} with bot-challenge signatures "
                        f"({', '.join(probe['challenge_signals'])}) while the "
                        "human-browser UA got 200. WAFs and bot-management layers "
                        "challenge spoofed-UA probes coming from non-vendor IPs; "
                        f"the real {ai_label} crawler fetches from its vendor's "
                        "published IP ranges and may be treated entirely "
                        "differently. This is evidence of bot-management "
                        "interference with THIS probe, not evidence of cloaking. "
                        "Verify what the real crawler receives via server logs "
                        "(geo-monitor's grep_ai_crawler_logs.py) before "
                        "concluding anything."
                    ),
                    "methodology_limitation": METHODOLOGY_LIMITATION,
                })
            elif probe["status"] in HARD_BLOCK_STATUSES or probe["status"] >= 500:
                result["findings"].append({
                    "url": url,
                    "ai_user_agent": ai_label,
                    "issue": "status_code_mismatch",
                    "severity": "high",
                    "ai_status": probe["status"],
                    "baseline_status": 200,
                    "detail": (
                        f"The spoofed {ai_label} User-Agent received HTTP "
                        f"{probe['status']} with no bot-challenge signatures while "
                        "the human-browser UA got 200 on both bracketing fetches. "
                        "A hard UA-conditional block is the strongest cloaking-"
                        "adjacent signal this probe can produce -- but it can "
                        "still be a bot-management rule matching on UA alone. "
                        "Verify against server logs before escalating."
                    ),
                    "methodology_limitation": METHODOLOGY_LIMITATION,
                })
            continue

        # Both probe and humans are 200: content comparison, judged against
        # BOTH human fetches and the self-consistency-scaled threshold.
        if probe["content_hash"] in (human_first["content_hash"], human_last["content_hash"]):
            continue
        gap_vs_first = _gap(probe["word_count"], human_first["word_count"])
        gap_vs_last = _gap(probe["word_count"], human_last["word_count"])
        if gap_vs_first >= effective_threshold and gap_vs_last >= effective_threshold:
            result["findings"].append({
                "url": url,
                "ai_user_agent": ai_label,
                "issue": "content_diverges",
                # Capped at medium by design: a word-count gap cannot
                # establish intent (personalization, A/B tests, consent
                # banners all produce gaps).
                "severity": "medium",
                "ai_word_count": probe["word_count"],
                "human_word_counts": [human_first["word_count"], human_last["word_count"]],
                "gap_ratio": round(min(gap_vs_first, gap_vs_last), 3),
                "gap_vs_first": round(gap_vs_first, 3),
                "gap_vs_last": round(gap_vs_last, 3),
                "natural_variance": round(natural_variance, 3),
                "effective_gap_threshold": round(effective_threshold, 3),
                "detail": (
                    f"Content served to the spoofed {ai_label} User-Agent diverges "
                    f"from BOTH bracketing human-browser fetches (gap "
                    f"{round(min(gap_vs_first, gap_vs_last), 3)} vs. threshold "
                    f"{round(effective_threshold, 3)}; the page's own natural "
                    f"variance between two human fetches was "
                    f"{round(natural_variance, 3)}). Intent is unknowable from a "
                    "diff -- investigate the cause before treating this as cloaking."
                ),
                "methodology_limitation": METHODOLOGY_LIMITATION,
            })

    return result


def main() -> None:
    import argparse
    import time

    parser = argparse.ArgumentParser(
        description=(
            "Diff content served to spoofed AI-crawler User-Agents vs. a "
            "self-consistent human-browser baseline to surface possible "
            "cloaking (red-flags.md §1, §5). UA-only probe -- see "
            "methodology_limitation in the output."
        )
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--urls", nargs="+", help="explicit list of URLs to check")
    group.add_argument("--sample-from-crawl", action="store_true",
                       help="sample pages from the latest crawl snapshot "
                            "(crawls fresh if none is recent)")
    parser.add_argument("--max-pages", type=int, default=20,
                        help="crawl cap when --sample-from-crawl needs a fresh crawl (default 20)")
    parser.add_argument("--sample-size", type=int, default=8,
                        help="how many crawled pages to spot-check (default 8)")
    args = parser.parse_args()

    cfg = config_module.load()
    snapshots.prune(cfg)

    snapshot_info = None
    if args.urls:
        urls = args.urls
    else:
        try:
            site_url = cfg.site_url
        except MissingConfigError as exc:
            report = {
                "urls_checked": [],
                "error": (
                    f"No site URL configured: {exc}. Pass --urls <url> [<url> ...] "
                    "explicitly, or run the seo-setup skill to write "
                    ".seo-engine/config.yml, or export SEO_SITE_URL."
                ),
            }
            json.dump(report, sys.stdout, indent=2)
            print()
            sys.exit(1)

        snap = snapshots.latest(cfg, max_age_hours=24)
        reused = snap is not None
        if snap is None:
            snap = snapshots.new_crawl(cfg, "geo-optimize", max_pages=args.max_pages)
        snapshot_info = {
            "path": snap.path.name,
            "producer_skill": snap.meta.get("producer_skill", ""),
            "reused": reused,
            "pages_crawled": snap.pages_crawled,
        }
        urls = []
        for record in snap.pages():
            if pagerules.is_indexable_html(record):
                urls.append(record.get("final_url") or record.get("url"))
            if len(urls) >= args.sample_size:
                break
        if not urls:
            summary = snap.meta.get("crawl_summary", {})
            snapshot_info["empty_crawl_reason"] = {
                "robots_status": summary.get("robots_status", ""),
                "all_blocked": summary.get("all_blocked", False),
            }
            urls = [site_url]

    results = [check_url(url) for url in urls]
    all_findings = [f for r in results for f in r["findings"]]
    all_findings.sort(key=lambda f: {"high": 0, "medium": 1, "low": 2}.get(f["severity"], 3))

    report = {
        "urls_checked": urls,
        "human_user_agent": HUMAN_UA,
        "probe_user_agents": dict(PROBE_USER_AGENTS),
        "gap_ratio_flag_threshold": BASE_GAP_RATIO_THRESHOLD,
        "threshold_rule": (
            "per URL: max(0.15, 3 x natural_variance), where natural_variance "
            "is the gap between two human-UA fetches bracketing the probes; a "
            "divergence must exceed the threshold against BOTH human fetches"
        ),
        "results": results,
        "findings": all_findings,
        "severity_counts": {
            "high": sum(1 for f in all_findings if f["severity"] == "high"),
            "medium": sum(1 for f in all_findings if f["severity"] == "medium"),
        },
        "methodology_limitation": METHODOLOGY_LIMITATION,
        "red_flags_ref": "red-flags.md §1 (Cloaking) and §5 (GEO-specific gotchas)",
        "auto_fixable": False,
        "human_review_reason": (
            "A content gap can be legitimate (A/B testing, personalization, "
            "consent/geo banners) or a real cloaking violation -- this script "
            "surfaces the diff, it does not determine intent. Investigate the "
            "cause on any flagged URL before concluding it's a problem."
        ),
    }
    if snapshot_info:
        report["snapshot"] = snapshot_info

    stamp = time.strftime("%Y%m%d-%H%M%S")
    report_path = cfg.reports_dir / f"geo-ai-cloaking-check-{stamp}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    state_path = cfg.state_dir / "geo-ai-cloaking-check-last-run.json"
    state_path.write_text(json.dumps({
        "urls_checked_count": len(urls),
        "severity_counts": report["severity_counts"],
        "report_path": str(report_path),
    }, indent=2), encoding="utf-8")

    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
