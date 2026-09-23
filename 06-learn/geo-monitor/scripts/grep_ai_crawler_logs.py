"""Free, zero-API-cost complementary GEO signal: grep a server access-log file
for known AI-crawler user-agent substrings and report hit counts per crawler.

Per references/geo-playbook.md section 9 ("Complementary, zero-API-cost
signals") and section 4 (the per-vendor crawler table this hardcoded list is
drawn from): this is the maintained ai-robots-txt/ai.robots.txt-style
approach -- an always-current, vendor-independent way to see which AI
crawlers actually visit the site, distinct from any dashboard.

Matching is CASE-INSENSITIVE (both the log line and every needle are
casefolded before comparison): real-world UA tokens do not always match the
vendor's documented capitalization -- e.g. Microsoft's crawler presents as
lowercase `bingbot/2.0`, which a case-sensitive `Bingbot` search would
permanently count as zero.

This script does NOT call any network API and needs no config.yml or API key
-- it only reads a local log file path given on the command line. It is
complementary to, not a replacement for, track_ai_visibility.py's citation
probing: a crawler hit means the crawler visited (necessary for citation on
platforms with a standing index -- see geo-playbook.md section 4), not that
the site was actually cited in a response.

Supported input: plain-text access logs in Common Log Format / Combined Log
Format (Apache/Nginx default) or any line-oriented log where the user-agent
string appears verbatim on the line (e.g. a JSON-lines log with a "user_agent"
or "ua" field is also matched, since this script does a substring search per
line rather than requiring strict CLF parsing). Supports .gz-compressed logs
transparently by extension.

--since-days parses the FULL CLF timestamp (`%d/%b/%Y:%H:%M:%S %z`), so the
cutoff is exact to the second and honors each line's own timezone offset --
not truncated to midnight UTC.

Privacy: client IPs in the sample lines persisted to reports are masked
(IPv4 -> first two octets + `.x.x`; IPv6 -> first hextet + `::x`). Counts are
unaffected -- only the stored sample text is masked.

Usage:
    python3 grep_ai_crawler_logs.py /var/log/nginx/access.log
    python3 grep_ai_crawler_logs.py /var/log/nginx/access.log.gz
    python3 grep_ai_crawler_logs.py access.log --sample-lines 3
    python3 grep_ai_crawler_logs.py access.log --since-days 30   # only lines whose
                                                                  # CLF/Combined-format
                                                                  # timestamp falls in
                                                                  # the last N days

Output: structured JSON to stdout, and a dated report written to
.seo-engine/reports/ IF run from within a repo that has scripts/lib/config.py
reachable (this script tries to locate cfg.reports_dir but degrades to
stdout-only if it can't -- see main() for the exact fallback).
"""

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
from scripts.lib import config as config_module

import argparse
import gzip
import ipaddress
import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from scripts.lib import http_util, snapshots

KNOWN_AI_CRAWLERS: list[dict[str, str]] = [
    {"user_agent": "GPTBot", "vendor": "OpenAI", "role": "training_only",
     "purpose": "Model training only -- no effect on ChatGPT search/citation."},
    {"user_agent": "OAI-SearchBot", "vendor": "OpenAI", "role": "citation_index",
     "purpose": "Powers ChatGPT search citations -- the one that matters for ChatGPT visibility."},
    {"user_agent": "ChatGPT-User", "vendor": "OpenAI", "role": "live_fetch",
     "purpose": "Live fetch during user actions/browsing -- not indexing."},
    {"user_agent": "ClaudeBot", "vendor": "Anthropic", "role": "training_only",
     "purpose": "Model training only -- no effect on Claude's live web-search citations."},
    {"user_agent": "Claude-SearchBot", "vendor": "Anthropic", "role": "citation_index",
     "purpose": "Indexing for Claude's search quality -- affects visibility/accuracy in citations."},
    {"user_agent": "Claude-User", "vendor": "Anthropic", "role": "live_fetch",
     "purpose": "Live fetch for user-directed web search."},
    {"user_agent": "PerplexityBot", "vendor": "Perplexity", "role": "citation_index",
     "purpose": "Builds/refreshes Perplexity's citation index."},
    {"user_agent": "Perplexity-User", "vendor": "Perplexity", "role": "live_fetch",
     "purpose": "Live fetch -- affects live-fetch, not the standing index."},
    {"user_agent": "Google-Extended", "vendor": "Google", "role": "training_only",
     "purpose": "Training/grounding for the Gemini app & Vertex AI -- does NOT affect "
                "AI Overview/AI Mode inclusion or ranking (standard Googlebot does that)."},
    {"user_agent": "Applebot-Extended", "vendor": "Apple", "role": "training_only",
     "purpose": "Training/Apple Intelligence generation (opt-out model) -- does not affect "
                "regular Applebot, which still powers Siri/Spotlight/Safari results."},
    {"user_agent": "Amazonbot", "vendor": "Amazon", "role": "citation_index",
     "purpose": "Indexing for Alexa/search answers."},
    {"user_agent": "bingbot", "vendor": "Bing/Copilot", "role": "citation_index",
     "purpose": "Single unified crawler for both classic Bing results AND Copilot citations "
                "-- no separate training-only bot exists to distinguish."},
    {"user_agent": "BingPreview", "vendor": "Bing/Copilot", "role": "citation_index",
     "purpose": "Page-snapshot/preview fetcher on the same unified Bing/Copilot index -- "
                "blocking it affects both classic Bing results and Copilot citations."},
    {"user_agent": "Bytespider", "vendor": "ByteDance", "role": "training_only",
     "purpose": "Model training for ByteDance LLMs -- no citation surface; widely reported "
                "to ignore robots.txt, so log evidence here is the reliable signal."},
    {"user_agent": "Meta-ExternalAgent", "vendor": "Meta", "role": "training_only",
     "purpose": "Model training / AI product improvement for Meta AI -- no effect on citations."},
    {"user_agent": "CCBot", "vendor": "Common Crawl", "role": "training_only",
     "purpose": "Builds the open Common Crawl corpus, widely used as LLM training data -- "
                "training only, no citation surface of its own."},
]

_CLF_TIMESTAMP_RE = re.compile(
    r"\[(\d{1,2})/([A-Za-z]{3})/(\d{4}):(\d{2}):(\d{2}):(\d{2})\s+([+-])(\d{2})(\d{2})\]"
)
_CLF_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

_IPV4_RE = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b")
_IPV6_CANDIDATE_RE = re.compile(r"\b[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{0,4}){2,7}\b")


def _mask_ipv4(match: "re.Match[str]") -> str:
    octets = [int(g) for g in match.groups()]
    if any(o > 255 for o in octets):
        return match.group(0)
    return f"{match.group(1)}.{match.group(2)}.x.x"


def _mask_ipv6(match: "re.Match[str]") -> str:
    candidate = match.group(0)
    try:
        ip = ipaddress.ip_address(candidate)
    except ValueError:
        return candidate
    if ip.version != 6:
        return candidate
    return f"{candidate.split(':', 1)[0]}::x"


def mask_client_ips(line: str) -> str:
    """Mask any IPv4/IPv6 address in a log line before it is persisted to a
    report: x.x.x.x -> first two octets + .x.x; IPv6 -> first hextet + ::x."""
    line = _IPV6_CANDIDATE_RE.sub(_mask_ipv6, line)
    return _IPV4_RE.sub(_mask_ipv4, line)


def _open_log(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, mode="rt", encoding="utf-8", errors="replace")
    return path.open(mode="rt", encoding="utf-8", errors="replace")


def _parse_clf_datetime(line: str) -> Optional[datetime]:
    """Full CLF timestamp (%d/%b/%Y:%H:%M:%S %z) as an aware datetime, or
    None if the line has no parseable timestamp."""
    match = _CLF_TIMESTAMP_RE.search(line)
    if not match:
        return None
    day, mon_str, year, hh, mm, ss, sign, tz_h, tz_m = match.groups()
    month = _CLF_MONTHS.get(mon_str.title())
    if month is None:
        return None
    offset = timedelta(hours=int(tz_h), minutes=int(tz_m))
    if sign == "-":
        offset = -offset
    try:
        return datetime(
            int(year), month, int(day), int(hh), int(mm), int(ss),
            tzinfo=timezone(offset),
        )
    except ValueError:
        return None


def scan_log(
    log_path: Path, crawlers: list[dict[str, str]], sample_lines: int, since_days: Optional[int],
) -> dict[str, Any]:
    cutoff = None
    if since_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

    needles = [(c["user_agent"], c["user_agent"].casefold()) for c in crawlers]

    counts: dict[str, int] = {c["user_agent"]: 0 for c in crawlers}
    samples: dict[str, list[str]] = {c["user_agent"]: [] for c in crawlers}
    total_lines = 0
    lines_with_timestamp = 0
    lines_excluded_by_since_days = 0
    other_bot_lines = 0

    generic_bot_markers = ("bot", "spider", "crawler")

    with _open_log(log_path) as f:
        for line in f:
            total_lines += 1
            if cutoff is not None:
                ts = _parse_clf_datetime(line)
                if ts is not None:
                    lines_with_timestamp += 1
                    if ts < cutoff:
                        lines_excluded_by_since_days += 1
                        continue

            folded_line = line.casefold()
            matched_known = False
            for ua, needle in needles:
                if needle in folded_line:
                    matched_known = True
                    counts[ua] += 1
                    if len(samples[ua]) < sample_lines:
                        samples[ua].append(mask_client_ips(line.rstrip("\n"))[:500])

            if not matched_known and any(marker in folded_line for marker in generic_bot_markers):
                other_bot_lines += 1

    return {
        "total_lines_scanned": total_lines,
        "lines_with_parseable_clf_timestamp": lines_with_timestamp,
        "lines_excluded_by_since_days": lines_excluded_by_since_days,
        "other_generic_bot_lines_not_matching_known_ai_crawlers": other_bot_lines,
        "counts": counts,
        "samples": samples,
    }


def build_report(log_path: Path, scan: dict[str, Any], since_days: Optional[int]) -> dict[str, Any]:
    rows = []
    for crawler in KNOWN_AI_CRAWLERS:
        ua = crawler["user_agent"]
        rows.append({
            "user_agent": ua,
            "vendor": crawler["vendor"],
            "role": crawler["role"],
            "purpose": crawler["purpose"],
            "hit_count": scan["counts"].get(ua, 0),
            "sample_lines": scan["samples"].get(ua, []),
        })
    rows.sort(key=lambda r: -r["hit_count"])

    total_ai_hits = sum(r["hit_count"] for r in rows)
    crawlers_seen = [r["user_agent"] for r in rows if r["hit_count"] > 0]
    crawlers_absent = [r["user_agent"] for r in rows if r["hit_count"] == 0]
    hits_by_role: dict[str, int] = {}
    for r in rows:
        hits_by_role[r["role"]] = hits_by_role.get(r["role"], 0) + r["hit_count"]

    return {
        "log_file": str(log_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since_days_filter": since_days,
        "scan_summary": {
            "total_lines_scanned": scan["total_lines_scanned"],
            "lines_with_parseable_clf_timestamp": scan["lines_with_parseable_clf_timestamp"],
            "lines_excluded_by_since_days": scan["lines_excluded_by_since_days"],
            "total_known_ai_crawler_hits": total_ai_hits,
            "hits_by_role": hits_by_role,
            "other_generic_bot_lines_not_matching_known_ai_crawlers": scan[
                "other_generic_bot_lines_not_matching_known_ai_crawlers"
            ],
            "known_ai_crawlers_seen": crawlers_seen,
            "known_ai_crawlers_absent": crawlers_absent,
        },
        "crawlers": rows,
        "sample_lines_note": (
            "Client IPs in sample_lines are masked before being persisted (IPv4 -> first "
            "two octets + .x.x; IPv6 -> first hextet + ::x). Hit counts are computed on the "
            "raw lines; only the stored samples are masked."
        ),
        "methodology_note": (
            "Case-insensitive substring match (both the log line and each needle are "
            "casefolded -- the real Bing crawler presents as lowercase `bingbot/2.0`) "
            "against the user-agent list hardcoded from references/geo-playbook.md section "
            "4's per-vendor table plus the ai-robots-txt/ai.robots.txt-style maintained "
            "training-corpus crawlers (Bytespider, Meta-ExternalAgent, CCBot) -- no external "
            "API call, no config required. --since-days parses the full CLF timestamp "
            "including time of day and timezone offset, so the cutoff is exact rather than "
            "midnight-UTC-truncated. A hit confirms the crawler visited; it does NOT confirm "
            "the page was actually cited in an AI response (that's what "
            "track_ai_visibility.py's citation probing measures). Per geo-playbook.md's "
            "Perplexity caveat (section 4): Cloudflare has documented undeclared 'stealth' "
            "crawlers impersonating Chrome and rotating ASNs, later attributed (disputed by "
            "Perplexity) to Perplexity-adjacent infrastructure -- so a zero PerplexityBot "
            "count here does not guarantee zero Perplexity crawl activity; treat this "
            "specific absence as inconclusive rather than a confirmed block."
        ),
        "interpretation_guidance": (
            "A crawler at zero hits is informative only if you know whether it SHOULD be "
            "visiting -- cross-check robots.txt (geo-optimize's crawler-access audit) before "
            "concluding a zero count means something was misconfigured. Use the `role` field: "
            "citation_index crawlers (OAI-SearchBot, Claude-SearchBot, PerplexityBot, "
            "Amazonbot, bingbot/BingPreview) at zero with real query volume elsewhere is a "
            "signal worth investigating, since their visits are a precondition for citation; "
            "live_fetch crawlers (ChatGPT-User, Claude-User, Perplexity-User) reflect live "
            "user actions, not the standing index; training_only crawlers (GPTBot, ClaudeBot, "
            "Google-Extended, Applebot-Extended, Bytespider, Meta-ExternalAgent, CCBot) at "
            "zero -- or at thousands of hits -- have no effect on citation either way (see "
            "geo-playbook.md section 4's 'Blocking it means' column)."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Grep a server access-log file for known AI-crawler user-agents "
                    "(case-insensitive) and report hit counts per crawler (free, "
                    "zero-API-cost GEO signal)."
    )
    parser.add_argument("log_file", help="Path to a plain-text (optionally .gz) access log.")
    parser.add_argument(
        "--sample-lines", type=int, default=2,
        help="Number of example matching log lines to keep per crawler (default 2). "
             "Client IPs in samples are masked before being persisted.",
    )
    parser.add_argument(
        "--since-days", type=int, default=None,
        help="Only count lines whose Common/Combined Log Format timestamp "
             "(%%d/%%b/%%Y:%%H:%%M:%%S %%z -- full time of day and timezone offset) falls "
             "within the last N days. Lines without a parseable timestamp are still counted "
             "(never silently dropped). Default: no time filtering.",
    )
    args = parser.parse_args()

    log_path = Path(args.log_file).expanduser().resolve()
    if not log_path.is_file():
        json.dump({
            "error": f"Log file not found: {log_path}",
            "note": "Pass the path to a plain-text or .gz-compressed access log as the "
                    "positional argument.",
        }, sys.stdout, indent=2)
        print()
        sys.exit(1)

    scan = scan_log(log_path, KNOWN_AI_CRAWLERS, args.sample_lines, args.since_days)
    report = build_report(log_path, scan, args.since_days)

    try:
        cfg = config_module.load()
        snapshots.prune(cfg)
        reports_dir = cfg.reports_dir
        ts = time.strftime("%Y%m%d-%H%M%S")
        report_path = reports_dir / f"ai-crawler-log-scan-{ts}.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        report["report_file"] = str(report_path)
    except Exception as exc:
        report["report_file"] = None
        report["report_write_skipped_reason"] = http_util.sanitize_text(str(exc))

    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
