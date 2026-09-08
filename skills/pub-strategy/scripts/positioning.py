"""pub-strategy: the editorial positioning that steers everything a
publication writes — strategy.yml.

Fields (see ../seo-references/publication-playbook.md §4, §6):
  client          name, domain, description, slogan (measured from the client site)
  direction       the steering prompt — the single highest-leverage input
  priority_topics what to write about      stances  points of view to take
  avoid_topics    what to steer clear of
  ranking_targets <= 5 phrases the client wants to be named for, each with
                  mention_framing and a basis (already_strong | white_space | positioning)
  landings        client URLs plus free-text "when it is worth citing" context; the
                  writer links one only when the context matches the section at hand
  competitors     name, domain, block_from_mentions
  brand_voice     writing_style, tone, kernel (voice card in pub-write)
  mention         degree off|subtle|woven, rate (share of articles that may carry one)

Explicit sets (--client-*, --direction, --mention-*) write immediately.
`--measure-brand` reads the client homepage; `--suggest` asks the LLM for a
full positioning draft grounded in that measurement, the publication
identity, the client's own page titles and any scraped competitor topics.
Both produce a PROPOSAL — nothing is written until `--apply`, mirroring the
review-then-commit pattern (ingest_context -> apply_context) of the vendor
API. Edit strategy.yml by hand for anything else; `--validate` checks it.

Usage:
    python3 positioning.py --publication llm-billboard --client-domain thrad.ai --client-name thrad \\
        --direction "how brands and agencies buy ads inside LLM assistants"
    python3 positioning.py --publication llm-billboard --measure-brand --suggest        # proposal only
    python3 positioning.py --publication llm-billboard --measure-brand --suggest --apply
    python3 positioning.py --publication llm-billboard --validate
"""

from __future__ import annotations

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

import argparse  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
from typing import Any, Optional  # noqa: E402
from urllib.parse import urlparse  # noqa: E402

from scripts.lib import http_util, llm, publication, pubstate, robots, sitemaps  # noqa: E402
from scripts.lib.config import Config  # noqa: E402

MAX_TARGETS = 5
SUGGEST_SYSTEM = (
    "You set the editorial positioning of an independent trade publication. The publication covers the client's "
    "CATEGORY for the client's buyers and is credible because it is not the client's blog. From the inputs, return "
    "ONLY JSON with: priority_topics (5-10 short topic phrases the publication should own), stances (3-6 opinionated "
    "points of view, each one sentence), avoid_topics (3-6 things it must not cover: off-category, the client's "
    "internal news, anything the client cannot credibly comment on), ranking_targets (up to 5 objects {phrase, basis, "
    "mention_framing}; phrase is a buyer query like 'best payroll software'; basis is already_strong, white_space or "
    "positioning; mention_framing says how an article may frame the client when that phrase is in play), competitors "
    "(up to 8 objects {name, domain, reason}), landings (up to 8 objects {url, context}; pick client URLs that a third "
    "party could honestly cite as a source — guides, data, docs — and say in one sentence when citing each is warranted). "
    "Never propose fabricated facts about the client."
)


def _publication(cfg: Config, slug: Optional[str]) -> tuple[Path, publication.Publication]:
    root = publication.find_publication(cfg, slug)
    return root, publication.load_publication(root)


def measure_brand(domain: str) -> dict[str, Any]:
    """Read the client homepage: description, slogan (og:title / h1), logo,
    socials, and sample page titles from its sitemap. Best-effort; every
    field may be empty."""
    from bs4 import BeautifulSoup

    site_url = domain if domain.startswith("http") else f"https://{domain}"
    out: dict[str, Any] = {"domain": urlparse(site_url).netloc, "site_url": site_url, "description": "", "slogan": "",
                           "title": "", "logo": "", "socials": [], "pages": [], "warnings": []}
    try:
        resp = http_util.get(site_url, timeout=30.0)
        soup = BeautifulSoup(resp.text, "lxml")
        out["title"] = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
        tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
        out["description"] = str(tag.get("content") or "").strip() if tag else ""
        h1 = soup.find("h1")
        out["slogan"] = h1.get_text(" ", strip=True)[:160] if h1 else ""
        logo = soup.find("link", attrs={"rel": lambda v: v and ("icon" in v or "apple-touch-icon" in v)})
        out["logo"] = str(logo.get("href") or "") if logo else ""
        socials = set()
        for a in soup.find_all("a", href=True):
            host = urlparse(a["href"]).netloc.lower()
            if any(s in host for s in ("linkedin.com", "x.com", "twitter.com", "github.com", "youtube.com", "instagram.com", "tiktok.com")):
                socials.add(a["href"])
        out["socials"] = sorted(socials)[:10]
    except Exception as exc:  # noqa: BLE001 — a measurement is best effort
        out["warnings"].append(f"homepage: {http_util.sanitize_text(str(exc))[:200]}")
    try:
        policy = robots.fetch(site_url)
        urls = sitemaps.fetch_url_set(site_url, policy, max_urls=500).get("page_urls", [])
        picks = [u for u in urls if re.search(r"/(blog|posts?|articles?|content|guides?|resources?|docs?|learn|insights?)/", u)][:12]
        picks = picks or urls[:12]
        for url in picks:
            try:
                r = http_util.get(url, timeout=20.0, min_interval=0.5)
                s = BeautifulSoup(r.text, "lxml")
                title = (s.title.string or "").strip() if s.title and s.title.string else url
                desc = s.find("meta", attrs={"name": "description"})
                out["pages"].append({"url": url, "title": title[:160], "description": (str(desc.get("content") or "")[:200] if desc else "")})
            except Exception:  # noqa: BLE001
                continue
    except Exception as exc:  # noqa: BLE001
        out["warnings"].append(f"sitemap: {http_util.sanitize_text(str(exc))[:200]}")
    return out


def _competitor_titles(root: Path, limit: int = 40) -> list[str]:
    titles: list[str] = []
    for f in sorted(pubstate.competitors_dir(root).glob("*.json")):
        for t in pubstate.load_json(f, {}).get("topics", []):
            if t.get("title"):
                titles.append(f"{t['title']} ({f.stem})")
    return titles[:limit]


def suggest(cfg: Config, root: Path, pub: publication.Publication, strategy: dict[str, Any], brand: Optional[dict[str, Any]]) -> dict[str, Any]:
    client = strategy["client"]
    brand = brand or {}
    pages = "\n".join(f"- {p['title']} — {p['url']}" for p in brand.get("pages", [])[:12]) or "(none read)"
    comp = "\n".join(f"- {t}" for t in _competitor_titles(root)) or "(none scraped yet — run scrape_competitors.py)"
    posts = "\n".join(f"- {p.title}" for p in pub.posts[:20]) or "(no posts yet)"
    user = (
        f"Client: {client.get('name') or brand.get('title')} ({client.get('domain') or brand.get('domain')})\n"
        f"Client description: {client.get('description') or brand.get('description')}\nClient slogan: {client.get('slogan') or brand.get('slogan')}\n"
        f"Client pages (citable):\n{pages}\n\nPublication: {pub.name} — {pub.tagline}\nSections: {', '.join(s['name'] for s in pub.sections)}\n"
        f"Editorial direction: {strategy.get('direction') or '(none — infer from the category)'}\n"
        f"Existing positioning (refine, do not discard what is good): {json.dumps({k: strategy.get(k) for k in ('priority_topics', 'stances', 'avoid_topics')})}\n"
        f"Competitor topics seen:\n{comp}\n\nAlready published here:\n{posts}"
    )
    data = llm.complete_json(cfg, SUGGEST_SYSTEM, user, max_tokens=4000)
    proposal = {
        "priority_topics": [str(x) for x in data.get("priority_topics", [])][:10],
        "stances": [str(x) for x in data.get("stances", [])][:6],
        "avoid_topics": [str(x) for x in data.get("avoid_topics", [])][:6],
        "ranking_targets": [{"phrase": str(t.get("phrase")), "basis": str(t.get("basis") or "positioning"),
                             "mention_framing": str(t.get("mention_framing") or ""), "status": "active", "source": "ai"}
                            for t in data.get("ranking_targets", []) if isinstance(t, dict) and t.get("phrase")][:MAX_TARGETS],
        "competitors": [{"name": str(c.get("name")), "domain": str(c.get("domain") or "").replace("https://", "").rstrip("/"),
                         "reason": str(c.get("reason") or ""), "block_from_mentions": False}
                        for c in data.get("competitors", []) if isinstance(c, dict) and c.get("domain")][:8],
        "landings": [{"url": str(l.get("url")), "context": str(l.get("context") or ""), "last_mentioned_at": None}
                     for l in data.get("landings", []) if isinstance(l, dict) and str(l.get("url", "")).startswith("http")][:8],
    }
    return proposal


def apply_proposal(strategy: dict[str, Any], proposal: dict[str, Any], brand: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Merge: AI lists replace AI lists but keep entries the owner marked source: user."""
    for key in ("priority_topics", "stances", "avoid_topics"):
        if proposal.get(key):
            strategy[key] = proposal[key]
    for key in ("ranking_targets", "competitors", "landings"):
        if proposal.get(key):
            manual = [x for x in strategy.get(key, []) if isinstance(x, dict) and x.get("source") == "user"]
            seen = {(x.get("phrase") or x.get("domain") or x.get("url")) for x in manual}
            strategy[key] = manual + [x for x in proposal[key] if (x.get("phrase") or x.get("domain") or x.get("url")) not in seen]
    strategy["ranking_targets"] = strategy.get("ranking_targets", [])[:MAX_TARGETS]
    if brand:
        for src, dst in (("description", "description"), ("slogan", "slogan"), ("domain", "domain")):
            if brand.get(src) and not strategy["client"].get(dst):
                strategy["client"][dst] = brand[src]
        if brand.get("socials"):
            strategy["client"]["socials"] = brand["socials"]
    return strategy


def validate(strategy: dict[str, Any], *, check_urls: bool) -> list[dict[str, str]]:
    problems: list[dict[str, str]] = []
    if not strategy["client"].get("domain"):
        problems.append({"severity": "error", "message": "client.domain is empty"})
    if not strategy.get("direction"):
        problems.append({"severity": "warning", "message": "direction is empty — it is the highest-leverage steering input"})
    if len(strategy.get("ranking_targets", [])) > MAX_TARGETS:
        problems.append({"severity": "error", "message": f"more than {MAX_TARGETS} ranking targets"})
    if not strategy.get("priority_topics"):
        problems.append({"severity": "warning", "message": "priority_topics is empty — run --suggest"})
    degree = (strategy.get("mention") or {}).get("degree")
    if degree not in ("off", "subtle", "woven"):
        problems.append({"severity": "error", "message": f"mention.degree must be off|subtle|woven (got {degree!r})"})
    rate = (strategy.get("mention") or {}).get("rate", 0)
    if not isinstance(rate, (int, float)) or not 0 <= float(rate) <= 1:
        problems.append({"severity": "error", "message": "mention.rate must be between 0 and 1"})
    for c in strategy.get("competitors", []):
        if "/" in str(c.get("domain", "")) or "://" in str(c.get("domain", "")):
            problems.append({"severity": "error", "message": f"competitor domain must be bare: {c.get('domain')}"})
    for l in strategy.get("landings", []):
        if not str(l.get("url", "")).startswith("http"):
            problems.append({"severity": "error", "message": f"landing url must be absolute: {l.get('url')}"})
        elif not l.get("context"):
            problems.append({"severity": "warning", "message": f"landing without context (when is it worth citing?): {l['url']}"})
        elif check_urls:
            try:
                resp = http_util.get(l["url"], timeout=20.0)
                if resp.status_code >= 400:
                    problems.append({"severity": "error", "message": f"landing returns HTTP {resp.status_code}: {l['url']}"})
            except Exception as exc:  # noqa: BLE001
                problems.append({"severity": "error", "message": f"landing unreachable: {l['url']} ({http_util.sanitize_text(str(exc))[:80]})"})
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Read, propose, apply and validate a publication's strategy.yml.")
    parser.add_argument("--publication", help="Publication slug")
    parser.add_argument("--client-domain", help="Set client.domain (bare domain)")
    parser.add_argument("--client-name", help="Set client.name")
    parser.add_argument("--direction", help="Set the editorial direction (steering prompt)")
    parser.add_argument("--mention-degree", choices=["off", "subtle", "woven"], help="Set mention.degree")
    parser.add_argument("--mention-rate", type=float, help="Set mention.rate (0..1 share of articles that may mention the client)")
    parser.add_argument("--measure-brand", action="store_true", help="Read the client homepage + sitemap into the proposal")
    parser.add_argument("--suggest", action="store_true", help="LLM-draft positioning as a proposal (needs an LLM key)")
    parser.add_argument("--apply", action="store_true", help="Write this run's proposal into strategy.yml")
    parser.add_argument("--validate", action="store_true", help="Check strategy.yml (targets cap, mention fields, landing URLs)")
    parser.add_argument("--check-urls", action="store_true", help="With --validate: HTTP-check every landing URL")
    parser.add_argument("--show", action="store_true", help="Print the effective strategy")
    parser.add_argument("--publications-dir", help="Override the publications directory")
    args = parser.parse_args()

    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    root, pub = _publication(cfg, args.publication)
    strategy = pubstate.load_strategy(root)
    result: dict[str, Any] = {"checked": True, "publication": root.name, "strategy_file": str(pubstate.strategy_path(root)), "notes": []}

    changed = False
    client_cfg = pub.site.get("client") or {}
    for key, value in (("domain", args.client_domain or (client_cfg.get("domain") if not strategy["client"].get("domain") else None)),
                       ("name", args.client_name or (client_cfg.get("name") if not strategy["client"].get("name") else None))):
        if value:
            strategy["client"][key] = str(value).replace("https://", "").rstrip("/")
            changed = True
    if args.direction:
        strategy["direction"] = args.direction
        changed = True
    elif not strategy.get("direction") and pub.site.get("direction"):
        strategy["direction"] = str(pub.site["direction"])
        changed = True
    if args.mention_degree:
        strategy["mention"]["degree"] = args.mention_degree
        changed = True
    if args.mention_rate is not None:
        strategy["mention"]["rate"] = args.mention_rate
        changed = True

    brand = None
    if args.measure_brand:
        domain = strategy["client"].get("domain")
        if not domain:
            parser.error("--measure-brand needs client.domain (pass --client-domain)")
        brand = measure_brand(domain)
        result["brand_measurement"] = brand
    proposal = None
    if args.suggest:
        if not llm.configured_providers(cfg):
            result["notes"].append("no LLM key configured — cannot --suggest; set ANTHROPIC_API_KEY / OPENAI_API_KEY / GOOGLE_GEMINI_API_KEY")
        else:
            proposal = suggest(cfg, root, pub, strategy, brand)
            result["proposal"] = proposal
    if args.apply:
        if proposal is None and brand is None:
            result["notes"].append("--apply had nothing to apply (use with --suggest and/or --measure-brand)")
        else:
            strategy = apply_proposal(strategy, proposal or {}, brand)
            changed = True
            result["applied"] = True
    elif proposal is not None or brand is not None:
        result["notes"].append("proposal only — rerun with --apply to write it into strategy.yml")
    if changed:
        pubstate.save_strategy(root, strategy)
        result["written"] = True
    if args.validate:
        result["validation"] = validate(strategy, check_urls=args.check_urls)
    if args.show or not any([args.suggest, args.measure_brand, args.validate, changed]):
        result["strategy"] = strategy
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if any(p["severity"] == "error" for p in result.get("validation", [])) else 0


if __name__ == "__main__":
    sys.exit(main())
