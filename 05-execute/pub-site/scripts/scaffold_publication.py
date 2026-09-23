"""Scaffold an owned editorial site with disclosed ownership and truthful
organization attribution. --author-name supplies actual contributors.
Legacy --authors/--deterministic-authors flags are accepted for migration;
fictional people and backdated biographies are no longer generated.
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
import hashlib  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Any, Optional  # noqa: E402
from urllib.parse import urlparse  # noqa: E402

import yaml  # noqa: E402

from scripts.lib import http_util, llm, publication  # noqa: E402
from scripts.lib.config import Config, save_site_config  # noqa: E402

DEFAULT_SECTIONS = ["Features", "Analysis"]
DEFAULT_AUTHOR_COUNT = 1

IDENTITY_SYSTEM = (
    "You name owned trade publications. Given a client company and an editorial direction, propose a "
    "publication identity that reads as a real, transparently owned outlet covering the client's CATEGORY — never the "
    "client itself. Hard rules: the name must not contain the client's company name or domain; 2-4 words; the "
    "tagline is ONE sentence under 140 characters describing what the publication covers and for whom; 2 to 4 "
    "sections, each a short noun phrase a newspaper would use as a nav label, with a one-sentence description. "
    "Return ONLY JSON: {\"name\": str, \"tagline\": str, \"sections\": [{\"name\": str, \"description\": str}]}."
)

def read_homepage(domain: str) -> dict[str, str]:
    from bs4 import BeautifulSoup

    url = domain if domain.startswith("http") else f"https://{domain}"
    resp = http_util.get(url, timeout=30.0)
    soup = BeautifulSoup(resp.text, "lxml")
    desc = ""
    tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if tag:
        desc = str(tag.get("content") or "")
    h1 = soup.find("h1")
    return {"title": (soup.title.string or "").strip() if soup.title and soup.title.string else "",
            "description": desc.strip(), "h1": h1.get_text(" ", strip=True) if h1 else ""}


def propose_identity(cfg: Config, client_domain: str, client_name: str, direction: str) -> dict[str, Any]:
    try:
        home = read_homepage(client_domain)
    except Exception as exc:  # noqa: BLE001 — an unreadable homepage is survivable when a direction is given
        home = {"title": "", "description": "", "h1": "", "error": http_util.sanitize_text(str(exc))}
    user = (f"Client company: {client_name or client_domain} ({client_domain})\n"
            f"Client homepage title: {home.get('title')}\nClient homepage description: {home.get('description')}\n"
            f"Client homepage H1: {home.get('h1')}\nEditorial direction: {direction or '(none given — infer the category)'}")
    data = llm.complete_json(cfg, IDENTITY_SYSTEM, user, max_tokens=2000)
    return {"name": str(data.get("name") or "").strip(), "tagline": str(data.get("tagline") or "").strip(),
            "sections": [{"name": str(s.get("name")), "description": str(s.get("description") or "")}
                         for s in data.get("sections", []) if isinstance(s, dict) and s.get("name")][:4],
            "homepage": home}


def _pick_theme(slug: str, wanted: Optional[str]) -> str:
    if wanted:
        if wanted not in publication.THEMES:
            raise SystemExit(f"Unknown theme {wanted!r}. Available: {', '.join(sorted(publication.THEMES))}")
        return wanted
    names = sorted(publication.THEMES)
    return names[int(hashlib.sha256(slug.encode()).hexdigest(), 16) % len(names)]


def build_plan(cfg: Config, args: argparse.Namespace) -> dict[str, Any]:
    notes: list[str] = []
    llm_ok = bool(llm.configured_providers(cfg))
    name, tagline = args.name, args.tagline
    sections: list[dict[str, Any]] = []
    if args.sections:
        sections = [{"name": s.strip(), "description": ""} for s in args.sections.split(",") if s.strip()]
    if (not name or not tagline or not sections) and args.from_domain:
        if llm_ok:
            proposed = propose_identity(cfg, args.from_domain, args.client_name or "", args.direction or "")
            name = name or proposed["name"]
            tagline = tagline or proposed["tagline"]
            sections = sections or proposed["sections"]
            notes.append("identity proposed by LLM from --from-domain/--direction; review before publishing")
        else:
            notes.append("no LLM key configured — cannot propose identity from --from-domain; pass --name/--tagline/--sections")
    if not name:
        raise SystemExit("--name is required (or --from-domain with an LLM key configured to propose one).")
    client_name = (args.client_name or "").strip()
    if client_name and client_name.lower() in name.lower() and not args.allow_client_name:
        raise SystemExit(
            f"Publication name {name!r} contains the client name {client_name!r}. A publication is an independent "
            f"outlet named after its subject, not the client (playbook §2). Pick another name or pass --allow-client-name.")
    slug = args.slug or publication.slugify(name, max_len=60)
    sections = sections or [{"name": s, "description": ""} for s in DEFAULT_SECTIONS]
    tagline = tagline or f"A publication on {args.direction or name.lower()}."
    if not args.tagline and not args.from_domain:
        notes.append("tagline defaulted — pass --tagline for a real one-sentence masthead description")
    section_names = [s["name"] for s in sections]
    if args.author_tenure != "real":
        raise SystemExit("Backdated fictional bylines are unsupported; supply real authors or use organization attribution.")
    names = args.author_name or [f"{name} Editorial Team"]
    authors = [{"slug": publication.slugify(n), "name": n,
                "type": "Person" if args.author_name else "Organization", "role": "Editorial contributor" if args.author_name else "Publisher",
                "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "city": "", "expertise": section_names,
                "bio": "Accountable editorial contributor supplied by the publisher." if args.author_name else
                       f"AI-assisted articles prepared for {name}, with accountable editorial review before publication."}
               for n in names]
    if args.authors != 1:
        notes.append("--authors is deprecated; use repeated --author-name for real contributors")
    site = {
        "name": name, "slug": slug, "tagline": tagline, "site_url": args.site_url.rstrip("/"),
        "language": args.language, "theme": _pick_theme(slug, args.theme), "icon": args.icon,
        "established": datetime.now(timezone.utc).year,
        "sections": [{"slug": publication.slugify(s["name"]), "name": s["name"], "description": s.get("description", "")}
                     for s in sections],
        "authors": authors,
        "disclosure": {"enabled": True,
                       "text": "Published by {client}. Articles may discuss the publisher’s products."},
        "client": {"name": client_name or name, "domain": (args.client_domain or args.from_domain or "").replace("https://", "").rstrip("/")},
        "direction": args.direction or "",
    }
    return {"slug": slug, "site": site, "notes": notes, "llm_configured": llm_ok}


def apply_plan(cfg: Config, plan: dict[str, Any], *, force: bool) -> dict[str, Any]:
    root = publication.publications_root(cfg) / plan["slug"]
    site_yml = root / "site.yml"
    if site_yml.exists() and not force:
        raise SystemExit(f"{site_yml} already exists — pass --force to overwrite site.yml (posts are never touched).")
    for sub in ("posts", "drafts", "assets", "static"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    site_yml.write_text(yaml.safe_dump(plan["site"], sort_keys=False, allow_unicode=True), encoding="utf-8")
    (root / ".gitignore").write_text("dist/\n", encoding="utf-8")
    registry = [p for p in (cfg.site.get("publications") or []) if isinstance(p, dict) and p.get("slug") != plan["slug"]]
    registry.append({"slug": plan["slug"], "site_url": plan["site"]["site_url"], "name": plan["site"]["name"]})
    save_site_config(cfg, {"publications": registry,
                           "publications_dir": str(cfg.site.get("publications_dir") or "publications")})
    return {"publication_dir": str(root), "site_yml": str(site_yml), "registered": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Scaffold a publication directory + site.yml.")
    parser.add_argument("--name", help="Masthead name (named after the subject, never the client)")
    parser.add_argument("--slug", help="Directory/URL slug (default: slugified name)")
    parser.add_argument("--site-url", required=True, help="Production URL, e.g. https://example-review.com")
    parser.add_argument("--tagline", help="One-sentence description shown under the masthead")
    parser.add_argument("--direction", help="Editorial direction in plain language (steers identity, sections, topics)")
    parser.add_argument("--from-domain", help="Client domain to infer the identity from (needs an LLM key)")
    parser.add_argument("--client-name", help="The brand this publication supports (name-collision rule, disclosure text)")
    parser.add_argument("--client-domain", help="The brand's domain (used by mention/landing logic downstream)")
    parser.add_argument("--sections", help="Comma-separated section names (2-4)")
    parser.add_argument("--author-name", action="append", help="Actual accountable author name (repeatable); default: editorial organization")
    parser.add_argument("--authors", type=int, default=DEFAULT_AUTHOR_COUNT, help="Legacy count flag; use --author-name for actual contributors")
    parser.add_argument("--author-tenure", choices=["backdated", "real"], default="real",
                        help="real uses today; backdated is rejected")
    parser.add_argument("--deterministic-authors", action="store_true", help="Legacy compatibility flag; never invents authors")
    parser.add_argument("--theme", help=f"One of: {', '.join(sorted(publication.THEMES))} (default: seeded pick)")
    parser.add_argument("--icon", default="spark", choices=sorted(publication.ICONS), help="Logo mark")
    parser.add_argument("--language", default="en")
    parser.add_argument("--disclosure", action="store_true", help="Compatibility flag; ownership disclosure is always enabled")
    parser.add_argument("--allow-client-name", action="store_true", help="Permit a name containing the client name")
    parser.add_argument("--publications-dir", help="Override the publications directory (default: publications/)")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan; write nothing")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing site.yml")
    args = parser.parse_args()

    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    if args.authors < 1:
        parser.error("--authors must be >= 1")
    if not urlparse(args.site_url).scheme:
        parser.error("--site-url must be a full URL, e.g. https://example.com")

    plan = build_plan(cfg, args)
    result: dict[str, Any] = {"checked": True, "dry_run": args.dry_run, "plan": plan}
    if not args.dry_run:
        result["applied"] = apply_plan(cfg, plan, force=args.force)
        result["next_steps"] = [
            f"Review {result['applied']['site_yml']} (name, tagline, sections, authors).",
            "Run pub-strategy positioning.py to write strategy.yml, then pub-curate build_topic_map.py.",
            f"Build with build_site.py --publication {plan['slug']} and validate with validate_site.py.",
        ]
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
