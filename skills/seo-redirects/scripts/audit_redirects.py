"""seo-redirects: redirect map safety audit.

Reads a crawl snapshot from the shared store (lib/snapshots.py — reusable
across skills within 24h) and classifies redirect behavior via the shared
lib/redirect_analysis taxonomy (same one seo-technical-audit uses, so the
two skills can never disagree about what a "loop" is):

  - redirect_loop — error_type too_many_redirects (a genuine loop raises;
    it never yields a followable chain) or a verbatim URL repeat. The ONLY
    launch-blocker-eligible redirect type (red-flags.md §4).
  - redirect_chain (>=2 substantive hops), canonicalization_chain (multi-hop
    but pure http->https->www normalization — low), normalizing_redirect
    (single-hop slash/www/scheme hygiene — info, never a defect), and
    link_to_redirect (internal links pointing at redirecting URLs).

Optionally accepts a path to a framework-specific redirect-config file (the
calling agent locates this first -- see SKILL.md "Locating the real redirect
source") and cross-checks declared rules against what the crawl actually
observed:

  - a rule declared in config but NOT honored live (source URL didn't
    redirect, or redirected somewhere other than the declared destination)
  - a redirect observed live that has NO matching declared rule (could be a
    platform-level/CDN redirect, a stale rule removed from config but still
    cached somewhere, or a rule defined in a config format this script's
    parser doesn't recognize -- flagged for human investigation, not assumed
    to be a bug)

Also accepts an optional list of "old URLs" (e.g. every URL a planned site
restructure will remove) to validate migration-safety: every old URL must
either still resolve (200) or have a redirect rule -- declared in config
and/or observed live -- pointing somewhere. Missing coverage here is a
launch blocker per SKILL.md, not a nice-to-have.

Config-file parsers are intentionally conservative regex/line-based
extractors, not full JS/Apache/Nginx parsers -- they are good enough to pull
out `(source, destination, status)` triples from the conventional shapes
each format uses, and any rule they can't confidently parse is surfaced in
`config_parse_warnings` rather than silently dropped.

Usage:
    python3 audit_redirects.py
    python3 audit_redirects.py --redirect-config /path/to/next.config.js
    python3 audit_redirects.py --old-urls-file old-urls.txt
    python3 audit_redirects.py --skip-crawl
"""

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse


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
from scripts.lib import crawler, redirect_analysis, snapshots, urlnorm  # noqa: E402


def load_pages(jsonl_path: Path) -> list[dict]:
    """Load a specific snapshot file passed via --snapshot (read-only)."""
    pages = []
    with jsonl_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                pages.append(json.loads(line))
    return pages


def _norm(url: str) -> str:
    """Trailing-slash-insensitive PATH comparison (config sources are paths).
    Full-URL identity comparisons use urlnorm.canonical_key instead."""
    return (url or "").rstrip("/")


# ---------------------------------------------------------------------------
# Chain/loop analysis: shared taxonomy from scripts.lib.redirect_analysis
# (the previous private detector flagged every /foo -> /foo/ slash-normalizing
# redirect as a critical "loop" — tripping launch blockers on healthy sites —
# while genuine loops raise TooManyRedirects upstream and never reached it)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Redirect-config file parsers
#
# Conservative, line/regex-based extraction of (source, destination, status)
# triples from each framework's conventional redirect declaration shape.
# Not a full parser for any of these languages — anything that doesn't match
# a recognized pattern is reported in `parse_warnings`, never silently
# dropped or guessed at.
# ---------------------------------------------------------------------------

def _detect_config_format(path: Path) -> str:
    name = path.name.lower()
    if name in ("next.config.js", "next.config.ts", "next.config.mjs", "next.config.cjs"):
        return "nextjs"
    if name == "vercel.json":
        return "vercel_json"
    if name == "_redirects":
        return "netlify_or_vercel_redirects_file"
    if name == ".htaccess":
        return "apache"
    if name.endswith(".conf") or "nginx" in name:
        return "nginx"
    return "unknown"


def parse_nextjs_redirects(text: str) -> dict:
    """Extract objects inside the array returned by an async redirects()
    function in next.config.js/ts. Looks for source/destination/permanent
    key-value triples within each `{ ... }` block inside the redirects
    array. This is a regex-based best-effort extraction, not a JS parser —
    template-literal or spread-based entries won't be recognized and will
    surface as a warning instead of a silently-missed rule."""
    rules = []
    warnings = []

    # Locate `return [` inside a redirects() function, then take the array by
    # BRACKET-DEPTH scanning — a non-greedy regex would truncate at the first
    # `]` inside a nested array (e.g. a `has: [...]` matcher), silently
    # dropping every later rule.
    fn_match = re.search(r"(?:async\s+)?redirects\s*\(\s*\)\s*(?::\s*[^\{]+)?\{", text)
    return_match = re.search(r"return\s*\[", text[fn_match.end():]) if fn_match else None
    if not fn_match or not return_match:
        warnings.append(
            "Could not locate a `redirects()` function returning an array in this file. "
            "If redirects are defined via a different pattern (e.g. imported from another "
            "module, or a middleware-based approach), this parser cannot see them — "
            "confirm manually."
        )
        return {"rules": rules, "parse_warnings": warnings}

    array_start = fn_match.end() + return_match.end() - 1  # index of the "["
    bracket_depth = 0
    array_end = None
    for idx in range(array_start, len(text)):
        ch = text[idx]
        if ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth -= 1
            if bracket_depth == 0:
                array_end = idx + 1
                break
    if array_end is None:
        warnings.append("Found `return [` in redirects() but its closing `]` was not — file truncated?")
        return {"rules": rules, "parse_warnings": warnings}

    array_text = text[array_start:array_end]
    # Split into top-level object blocks by tracking brace depth.
    blocks = []
    depth = 0
    current = ""
    for ch in array_text:
        if ch == "{":
            depth += 1
        if depth > 0:
            current += ch
        if ch == "}":
            depth -= 1
            if depth == 0 and current.strip():
                blocks.append(current)
                current = ""

    for block in blocks:
        source_m = re.search(r"source\s*:\s*['\"`]([^'\"`]+)['\"`]", block)
        dest_m = re.search(r"destination\s*:\s*['\"`]([^'\"`]+)['\"`]", block)
        permanent_m = re.search(r"permanent\s*:\s*(true|false)", block)
        if source_m and dest_m:
            rules.append({
                "source": source_m.group(1),
                "destination": dest_m.group(1),
                "status": 308 if (permanent_m and permanent_m.group(1) == "true") else
                          307 if permanent_m else None,
                "permanent": permanent_m.group(1) == "true" if permanent_m else None,
            })
        else:
            warnings.append(
                f"Found a redirect object block that didn't match the expected "
                f"source/destination shape: {block.strip()[:200]}"
            )
    return {"rules": rules, "parse_warnings": warnings}


def parse_vercel_json(text: str) -> dict:
    """vercel.json `redirects` array: [{ "source": ..., "destination": ...,
    "permanent": bool | "statusCode": int }]."""
    rules = []
    warnings = []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"rules": [], "parse_warnings": [f"vercel.json is not valid JSON: {exc}"]}

    entries = data.get("redirects", [])
    if not isinstance(entries, list):
        return {"rules": [], "parse_warnings": ["vercel.json 'redirects' key is not an array"]}

    for entry in entries:
        if not isinstance(entry, dict) or "source" not in entry or "destination" not in entry:
            warnings.append(f"Skipping malformed vercel.json redirect entry: {entry}")
            continue
        status = entry.get("statusCode")
        if status is None:
            # Vercel's documented default for an absent `permanent` is false.
            status = 308 if entry.get("permanent") else 307
        rules.append({
            "source": entry["source"],
            "destination": entry["destination"],
            "status": status,
            "permanent": entry.get("permanent"),
        })
    return {"rules": rules, "parse_warnings": warnings}


def parse_redirects_file(text: str) -> dict:
    """Netlify/Vercel `_redirects` plain-text format:
    `/old-path  /new-path  301` (whitespace-separated, one rule per line,
    `#` comments, blank lines ignored)."""
    rules = []
    warnings = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            warnings.append(f"Line {lineno}: could not parse '{raw}' as a redirect rule")
            continue
        source, destination = parts[0], parts[1]
        status = 301
        if len(parts) >= 3 and parts[2].isdigit():
            status = int(parts[2])
        rules.append({"source": source, "destination": destination, "status": status, "permanent": None})
    return {"rules": rules, "parse_warnings": warnings}


def parse_apache_htaccess(text: str) -> dict:
    """Apache .htaccess: `Redirect [status] /old /new` and
    `RedirectMatch [status] regex /new` directives. RewriteRule directives
    are intentionally NOT parsed (their flags/backreferences make a
    reliable regex-based translation to a static source/destination pair
    unsafe) — they're surfaced as a warning so a human confirms coverage
    for any RewriteRule-based redirects instead of this script silently
    missing them."""
    rules = []
    warnings = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(
            r"Redirect(Match)?\s+(?:(\d{3}|permanent|temp)\s+)?(\S+)\s+(\S+)",
            line, re.IGNORECASE,
        )
        if m:
            is_match, status_token, source, destination = m.groups()
            status = 301
            if status_token:
                if status_token.isdigit():
                    status = int(status_token)
                elif status_token.lower() == "temp":
                    status = 302
            rules.append({
                "source": source,
                "destination": destination,
                "status": status,
                "permanent": status in (301, 308),
                "is_regex_match": bool(is_match),
            })
        elif re.match(r"RewriteRule\b", line, re.IGNORECASE):
            warnings.append(
                f"Line {lineno}: RewriteRule directive not parsed (regex/flag semantics "
                f"are too complex to translate safely into a static source/destination "
                f"pair): '{raw.strip()}'. Confirm coverage for this rule manually."
            )
    return {"rules": rules, "parse_warnings": warnings}


def parse_nginx_conf(text: str) -> dict:
    """Nginx: `return 301 https://...;` inside a `location` block, and
    `rewrite ^/old$ /new permanent;` directives. Location-block context is
    tracked loosely (line-based) to associate a `return`/`rewrite` with its
    enclosing `location` path where possible."""
    rules = []
    warnings = []
    current_location = None
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        loc_m = re.match(r"location\s*(?:=|~\*?)?\s*([^\s{]+)\s*\{", line)
        if loc_m:
            current_location = loc_m.group(1)
            continue
        if line == "}":
            current_location = None
            continue

        return_m = re.match(r"return\s+(\d{3})\s+(\S+?);?\s*$", line)
        if return_m:
            status, destination = return_m.groups()
            rules.append({
                "source": current_location or "(unknown location block)",
                "destination": destination.strip('"\''),
                "status": int(status),
                "permanent": int(status) in (301, 308),
            })
            continue

        rewrite_m = re.match(
            r"rewrite\s+(\S+)\s+(\S+)\s*(permanent|redirect)?;?\s*$", line
        )
        if rewrite_m:
            pattern, destination, flag = rewrite_m.groups()
            rules.append({
                "source": pattern,
                "destination": destination,
                "status": 301 if flag == "permanent" else (302 if flag == "redirect" else None),
                "permanent": flag == "permanent",
                "is_regex_match": True,
            })
    if not rules:
        warnings.append(
            "No `return <status> <url>;` or `rewrite ... permanent|redirect;` directives "
            "found — this config may use a different redirect mechanism (e.g. a map file, "
            "an included file this parser didn't follow, or a third-party module)."
        )
    return {"rules": rules, "parse_warnings": warnings}


CONFIG_PARSERS = {
    "nextjs": parse_nextjs_redirects,
    "vercel_json": parse_vercel_json,
    "netlify_or_vercel_redirects_file": parse_redirects_file,
    "apache": parse_apache_htaccess,
    "nginx": parse_nginx_conf,
}


def parse_redirect_config(path: Path) -> dict:
    fmt = _detect_config_format(path)
    if fmt == "unknown":
        return {
            "checked": False,
            "format": "unknown",
            "reason": (
                f"Could not recognize the redirect-config format of {path.name}. "
                "Supported: next.config.js/ts/mjs/cjs (Next.js redirects()), "
                "vercel.json (redirects array), _redirects (Netlify/Vercel plain-text), "
                ".htaccess (Apache Redirect/RedirectMatch), nginx *.conf (return/rewrite). "
                "If this is a CMS-level redirect manager, there is no file to parse — "
                "query the CMS's own redirect table/API instead."
            ),
            "rules": [],
            "parse_warnings": [],
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    result = CONFIG_PARSERS[fmt](text)
    return {
        "checked": True,
        "format": fmt,
        "path": str(path),
        "rules": result["rules"],
        "parse_warnings": result["parse_warnings"],
    }


# ---------------------------------------------------------------------------
# Cross-check: declared config rules vs. what the crawl actually observed
# ---------------------------------------------------------------------------

def _path_matches_source(source: str, url_path: str) -> bool:
    """Loose match: exact path match, or a simple wildcard/:param pattern
    treated as a prefix match up to the first wildcard/param token. This is
    intentionally forgiving (not a full path-to-regex compiler) — good
    enough to associate a crawled URL with the rule that most likely
    produced it, while any ambiguous match is still reported with the raw
    strings so a human can verify."""
    if source == url_path:
        return True
    if "*" in source:
        prefix = source.split("*", 1)[0]
        return url_path.startswith(prefix)
    if ":" in source:
        prefix = source.split(":", 1)[0]
        return url_path.startswith(prefix) if prefix else False
    return False


def crosscheck_config_vs_crawl(rules: list[dict], pages: list[dict], site_url: str) -> dict:
    """For each declared rule, find the crawled page whose URL path matches
    `source`, and compare what the crawl actually observed against the
    declared `destination`. Also flag live-observed redirects (chains found
    in the crawl) that have no matching declared rule at all."""
    site_parsed = urlparse(site_url)
    by_path: dict[str, dict] = {}
    for p in pages:
        path = urlparse(p["url"]).path or "/"
        by_path[path] = p

    mismatches = []
    confirmed = []
    for rule in rules:
        source_path = urlparse(rule["source"]).path if rule["source"].startswith("http") else rule["source"]
        matched_page = None
        for path, page in by_path.items():
            if _path_matches_source(source_path, path):
                matched_page = page
                break

        if matched_page is None:
            mismatches.append({
                "type": "declared_rule_not_observed",
                "severity": "medium",
                "declared_source": rule["source"],
                "declared_destination": rule["destination"],
                "detail": (
                    f"Config declares a redirect from '{rule['source']}' to "
                    f"'{rule['destination']}', but no crawled URL matched this source "
                    "path — either the source path was never linked/crawled (so this "
                    "couldn't be verified live), or the rule isn't actually being "
                    "honored by the running site."
                ),
                "auto_fixable": False,
                "human_review_reason": (
                    "Confirm live by requesting the declared source URL directly "
                    "(e.g. curl -I) — the crawl only follows links it discovers, so an "
                    "unlinked old URL wouldn't appear here even if the rule works fine."
                ),
            })
            continue

        observed_final = _norm(matched_page.get("final_url") or matched_page.get("url", ""))
        declared_dest = rule["destination"]
        declared_dest_path = urlparse(declared_dest).path if declared_dest.startswith("http") else declared_dest
        observed_path = urlparse(observed_final).path or "/"

        is_redirect_observed = bool(matched_page.get("redirect_chain")) or matched_page.get("status") in (
            301, 302, 303, 307, 308,
        )

        if not is_redirect_observed:
            mismatches.append({
                "type": "declared_rule_not_honored",
                "severity": "high",
                "declared_source": rule["source"],
                "declared_destination": rule["destination"],
                "observed_url": matched_page["url"],
                "observed_status": matched_page.get("status"),
                "detail": (
                    f"Config declares '{rule['source']}' should redirect to "
                    f"'{rule['destination']}', but the live crawl observed HTTP "
                    f"{matched_page.get('status')} with no redirect at that path — the "
                    "rule does not appear to be active on the running site."
                ),
                "red_flags_ref": "red-flags.md §4",
                "auto_fixable": False,
                "human_review_reason": (
                    "Could indicate the rule was added to config but not deployed, is "
                    "shadowed by an earlier-matching rule, or the config file checked "
                    "isn't actually the one governing production. Verify deployment "
                    "and rule ordering before assuming it's simply broken."
                ),
            })
        elif observed_path.rstrip("/") != declared_dest_path.rstrip("/"):
            mismatches.append({
                "type": "declared_rule_destination_mismatch",
                "severity": "high",
                "declared_source": rule["source"],
                "declared_destination": rule["destination"],
                "observed_final_url": observed_final,
                "detail": (
                    f"Config declares '{rule['source']}' should redirect to "
                    f"'{rule['destination']}', but the live crawl observed it landing "
                    f"at '{observed_final}' instead."
                ),
                "red_flags_ref": "red-flags.md §4",
                "auto_fixable": False,
                "human_review_reason": (
                    "A rule-ordering conflict (an earlier rule intercepting the same "
                    "source path) or a stale config file is the likely cause — needs "
                    "source-level investigation, not a guess-and-fix."
                ),
            })
        else:
            confirmed.append({
                "declared_source": rule["source"],
                "declared_destination": rule["destination"],
                "observed_final_url": observed_final,
            })

    # Live redirects observed in the crawl with no declared rule matching
    # their source path at all.
    declared_sources = [
        (urlparse(r["source"]).path if r["source"].startswith("http") else r["source"])
        for r in rules
    ]
    undeclared = []
    for p in pages:
        if not p.get("redirect_chain"):
            continue
        path = urlparse(p["url"]).path or "/"
        if any(_path_matches_source(src, path) for src in declared_sources):
            continue
        undeclared.append({
            "type": "live_redirect_not_declared_in_config",
            "severity": "low",
            "url": p["url"],
            "hop_sequence": p.get("redirect_chain", []) + ([p.get("final_url", "")] if p.get("final_url") else []),
            "detail": (
                f"{p['url']} redirects live, but no rule in the checked config file "
                "declares this source path. This may be a platform/CDN-level redirect, "
                "a rule defined in a different config location, or a stale rule this "
                "parser's format doesn't recognize — investigate rather than assume "
                "it's undocumented shadow behavior."
            ),
            "auto_fixable": False,
        })

    return {
        "rules_checked": len(rules),
        "confirmed_count": len(confirmed),
        "mismatch_count": len(mismatches),
        "confirmed": confirmed,
        "mismatches": mismatches,
        "undeclared_live_redirects": undeclared,
    }


# ---------------------------------------------------------------------------
# Migration-safety: every "old URL" must have live coverage
# ---------------------------------------------------------------------------

def check_migration_coverage(old_urls: list[str], pages: list[dict], config_rules: list[dict]) -> dict:
    """For each URL slated to stop existing in a migration, confirm it
    either still resolves 200 (not actually being removed / not yet) or has
    SOME redirect coverage — either observed live in the crawl, or declared
    in the config file (in case the crawl never reached/discovered that old
    URL, which is expected once it's been unlinked in prep for the
    migration)."""
    by_key = {urlnorm.canonical_key(p["url"]): p for p in pages}
    declared_sources = {
        (urlparse(r["source"]).path if r["source"].startswith("http") else r["source"]).rstrip("/")
        for r in config_rules
    }

    covered = []
    missing = []
    for old_url in old_urls:
        old_url = old_url.strip()
        if not old_url:
            continue
        path = urlparse(old_url).path or "/"
        page = by_key.get(urlnorm.canonical_key(old_url))

        if page and page.get("error_type") == "too_many_redirects":
            # A redirect exists but it LOOPS — worse than no coverage.
            missing.append({
                "old_url": old_url,
                "reason": "redirect_loops",
                "detail": (
                    f"{old_url} has a redirect rule, but it enters a redirect loop — "
                    "the destination is unreachable. Fix the loop before launch."
                ),
            })
            continue

        has_live_redirect = bool(page and page.get("redirect_chain") and not page.get("error"))
        has_live_200 = bool(page and page.get("status") == 200 and not page.get("redirect_chain"))
        has_declared_rule = path.rstrip("/") in declared_sources or any(
            _path_matches_source(src, path) for src in declared_sources
        )

        if has_live_redirect or has_declared_rule:
            covered.append({
                "old_url": old_url,
                "covered_by": "live_redirect" if has_live_redirect else "declared_config_rule",
                "destination": (page.get("final_url") if has_live_redirect else None),
            })
        elif has_live_200:
            missing.append({
                "old_url": old_url,
                "reason": "still_live_200_no_redirect_planned",
                "detail": (
                    f"{old_url} currently returns 200 with no redirect in place. If this "
                    "URL is genuinely being removed/changed in the migration, a redirect "
                    "rule must be added before launch — there is currently no planned "
                    "target for it."
                ),
            })
        else:
            missing.append({
                "old_url": old_url,
                "reason": "no_redirect_and_not_currently_reachable",
                "detail": (
                    f"{old_url} was not found as a live 200 page, does not have an "
                    "observed live redirect, and matches no declared rule in the config "
                    "file checked. If this URL previously existed (had backlinks/rankings) "
                    "and is being removed, this is missing redirect coverage — treat as a "
                    "launch blocker per SKILL.md, since lost backlink/ranking signal from "
                    "an unredirected URL is often unrecoverable."
                ),
            })

    return {
        "old_url_count": len([u for u in old_urls if u.strip()]),
        "covered_count": len(covered),
        "missing_count": len(missing),
        "covered": covered,
        "missing": missing,
        "launch_blocker": len(missing) > 0,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="seo-redirects: redirect chain/loop audit, config cross-check, migration-safety validation"
    )
    parser.add_argument("--max-pages", type=int, default=crawler.DEFAULT_MAX_PAGES)
    parser.add_argument("--delay", type=float, default=crawler.CRAWL_DELAY_SECONDS)
    parser.add_argument("--ignore-robots", action="store_true",
                         help="only for your own localhost/staging builds")
    parser.add_argument("--skip-crawl", action="store_true",
                         help="reuse the most recent shared snapshot (< 24h old) instead of re-crawling")
    parser.add_argument("--snapshot", type=str, default=None,
                         help="path to a specific crawl snapshot JSONL to analyze read-only "
                              "(implies --skip-crawl; the file is never overwritten)")
    parser.add_argument("--redirect-config", type=str, default=None,
                         help="path to the target repo's redirect-config file "
                              "(next.config.js/ts, vercel.json, _redirects, .htaccess, nginx *.conf) "
                              "for the declared-vs-observed cross-check")
    parser.add_argument("--old-urls-file", type=str, default=None,
                         help="path to a text file, one URL per line, of URLs a planned "
                              "migration will remove — validates every one has redirect coverage")
    args = parser.parse_args()

    cfg = config_module.load()
    site_url = cfg.site_url

    if args.snapshot:
        # Analyze an explicitly named snapshot, read-only — never overwrite it.
        snapshot_path = Path(args.snapshot)
        if not snapshot_path.is_file():
            json.dump({"error": f"--snapshot path does not exist: {snapshot_path}"}, sys.stdout, indent=2)
            print()
            sys.exit(1)
        pages = load_pages(snapshot_path)
        crawl_summary = {"reused_named_snapshot": True, "snapshot_path": str(snapshot_path)}
    else:
        snap = snapshots.latest(cfg, max_age_hours=24) if args.skip_crawl else None
        if snap is None:
            snap = snapshots.new_crawl(
                cfg, "seo-redirects",
                max_pages=args.max_pages, delay=args.delay, ignore_robots=args.ignore_robots,
            )
            crawl_summary = dict(snap.meta.get("crawl_summary", {}))
        else:
            crawl_summary = {"reused_existing_snapshot": True,
                             "produced_by": snap.meta.get("producer_skill", "unknown")}
        crawl_summary["snapshot_path"] = str(snap.path)
        pages = list(snap.pages())
        if snap.meta.get("crawl_summary", {}).get("all_blocked"):
            json.dump({
                "error": (
                    "Crawl produced zero pages: robots.txt "
                    f"({snap.meta['crawl_summary'].get('robots_status')}) blocked everything. "
                    "Use --ignore-robots only for your own staging build."
                ),
            }, sys.stdout, indent=2)
            print()
            sys.exit(1)

    taxonomy = redirect_analysis.classify_snapshot(pages)
    loop_findings = taxonomy["findings"]["redirect_loop"]
    chain_findings = taxonomy["findings"]["redirect_chain"]
    canonicalization_findings = taxonomy["findings"]["canonicalization_chain"]
    link_to_redirect_findings = taxonomy["findings"]["link_to_redirect"]

    all_findings = (loop_findings + chain_findings
                    + canonicalization_findings + link_to_redirect_findings)

    # --- optional config cross-check ---
    config_result = {"checked": False, "reason": "No --redirect-config path supplied."}
    crosscheck_result = None
    if args.redirect_config:
        config_path = Path(args.redirect_config)
        if not config_path.is_file():
            config_result = {
                "checked": False,
                "reason": f"--redirect-config path does not exist: {config_path}",
            }
        else:
            config_result = parse_redirect_config(config_path)
            if config_result.get("checked") and config_result.get("rules"):
                crosscheck_result = crosscheck_config_vs_crawl(config_result["rules"], pages, site_url)
                for m in crosscheck_result["mismatches"]:
                    all_findings.append(m)
                for u in crosscheck_result["undeclared_live_redirects"]:
                    all_findings.append(u)

    # --- optional migration-safety check ---
    migration_result = {"checked": False, "reason": "No --old-urls-file supplied."}
    if args.old_urls_file:
        old_urls_path = Path(args.old_urls_file)
        if not old_urls_path.is_file():
            migration_result = {
                "checked": False,
                "reason": f"--old-urls-file path does not exist: {old_urls_path}",
            }
        else:
            old_urls = old_urls_path.read_text(encoding="utf-8").splitlines()
            config_rules = config_result.get("rules", []) if config_result.get("checked") else []
            migration_result = check_migration_coverage(old_urls, pages, config_rules)
            migration_result["checked"] = True
            for m in migration_result["missing"]:
                all_findings.append({
                    "type": "missing_migration_redirect",
                    "severity": "critical",
                    "url": m["old_url"],
                    "detail": m["detail"],
                    "red_flags_ref": "red-flags.md §4 (Redirect chains and loops); §2 (Manual actions — recovery requires complete coverage, not a partial fix)",
                    "auto_fixable": False,
                    "human_review_reason": (
                        "Treat as a launch blocker, not a nice-to-have — lost backlink/ranking "
                        "signal from an unredirected URL during a migration is often "
                        "unrecoverable. A human/agent must add the correct 301 target before "
                        "the migration ships."
                    ),
                })

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    all_findings.sort(key=lambda f: severity_order.get(f.get("severity", "low"), 9))

    severity_counts: dict[str, int] = {}
    for f in all_findings:
        severity_counts[f.get("severity", "unknown")] = severity_counts.get(f.get("severity", "unknown"), 0) + 1

    report = {
        "site_url": site_url,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "crawl_summary": crawl_summary,
        "pages_analyzed": len(pages),
        "severity_counts": severity_counts,
        "redirect_loops": {
            "count": len(loop_findings),
            "findings": loop_findings,
        },
        "redirect_chains": {
            "count": len(chain_findings),
            "findings": chain_findings,
        },
        "canonicalization_chains": {
            "count": len(canonicalization_findings),
            "findings": canonicalization_findings,
        },
        "links_to_redirects": {
            "count": len(link_to_redirect_findings),
            "findings": link_to_redirect_findings,
        },
        "normalizing_redirects_observed": taxonomy["counts"]["normalizing_redirect"],
        "config_crosscheck": {
            "checked": config_result.get("checked", False),
            "reason": config_result.get("reason"),
            "config_format": config_result.get("format"),
            "config_path": config_result.get("path"),
            "rules_found_in_config": len(config_result.get("rules", [])),
            "parse_warnings": config_result.get("parse_warnings", []),
            "crosscheck": crosscheck_result,
        },
        "migration_safety": migration_result,
        # Only genuinely destination-unreachable problems block a launch:
        # real loops and unredirected migration URLs — never chain hygiene.
        "launch_blocker": bool(migration_result.get("launch_blocker")) or len(loop_findings) > 0,
        "findings": all_findings,
    }

    dated_report_path = cfg.reports_dir / f"redirects-audit-{time.strftime('%Y-%m-%d')}.json"
    dated_report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["_report_path"] = str(dated_report_path)

    snapshots.prune(cfg)

    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
