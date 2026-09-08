"""pub-site: scaffold a new publication (an independent editorial site the
pub-* pipeline writes into and build_site.py renders).

Mirrors the provisioning contract observed in Letterstory's phantom-blog
API (see ../seo-references/publication-playbook.md §2, §5):
  * the masthead is named after the SUBJECT, never after the client — a
    name containing the client's company name is rejected;
  * a one-sentence tagline; a theme from the theme table; an icon mark;
  * 2-4 sections (the topic-map pillars double as the site's nav);
  * a bank of recurring authors with role, city, bio and a `started_at`
    that predates the site (the byline policy chosen for this repo —
    playbook §5 — is to mirror Letterstory exactly; flip
    `--author-tenure real` to date bylines from the first post instead);
  * disclosure off by default, `--disclosure` turns the /about line on.

Two modes:
  --dry-run   compute and print the plan (name, tagline, sections, authors,
              theme) without writing anything — review it, tweak flags, rerun.
  (default)   write <publications_dir>/<slug>/{site.yml, posts/, drafts/,
              assets/, static/} and register the publication in
              .seo-engine/config.yml under `publications`.

Identity comes from flags, or — with an LLM key configured — is proposed
from `--from-domain <client domain>` plus `--direction "<editorial
direction in plain language>"`, the highest-leverage steering input.
Without an LLM key the script still works: authors and sections are
generated deterministically from a name bank, seeded by the slug, so
repeated runs give the same masthead.

Usage:
    python3 scaffold_publication.py --name "LLM Billboard" --site-url https://llmbillboard.com \\
        --tagline "A blog on conversational AI advertising." --sections "Advertiser Strategy,AI Search" \\
        --client-name thrad --client-domain thrad.ai --theme signal --dry-run
    python3 scaffold_publication.py --from-domain thrad.ai --direction "how agency trading desks buy ads inside LLMs" \\
        --site-url https://adsinllms.com --client-name thrad
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

ROLES = ["Staff Writer", "Senior Writer", "Features Editor", "Editor at Large", "Columnist",
         "Reporter", "Correspondent", "Contributing Editor"]
FIRST_NAMES = ["Anaya", "Leila", "Ezra", "Maya", "Omar", "Selin", "Simone", "Sofia", "Soren", "Cyrus", "Dara",
               "Lena", "Kai", "Kwame", "Lucia", "Malik", "Rafael", "Amara", "Hassan", "Ingrid", "Marcus",
               "Naomi", "Talia", "Felix", "Priya", "Jonas", "Mateo", "Zara"]
LAST_NAMES = ["Contreras", "Halvorsen", "Haddad", "Moreau", "Mbeki", "Kowalski", "Rossi", "Sørensen", "Wexler",
              "Zola", "Osei", "Petrova", "Yamada", "Alvarez", "Nair", "Vance", "Ford", "Sabatini", "Novak",
              "Bennett", "Okafor", "Lindqvist", "Tanaka", "Ruiz"]
CITIES = ["Berlin", "Dublin", "Lisbon", "Austin", "Toronto", "Amsterdam", "Singapore", "Melbourne", "Chicago",
          "Copenhagen", "Barcelona", "Seattle", "Montreal", "Stockholm", "Denver", "Edinburgh"]
DEFAULT_SECTIONS = ["Features", "Analysis"]
DEFAULT_AUTHOR_COUNT = 8

IDENTITY_SYSTEM = (
    "You name independent trade publications. Given a client company and an editorial direction, propose a "
    "publication identity that reads as a real, independent outlet covering the client's CATEGORY — never the "
    "client itself. Hard rules: the name must not contain the client's company name or domain; 2-4 words; the "
    "tagline is ONE sentence under 140 characters describing what the publication covers and for whom; 2 to 4 "
    "sections, each a short noun phrase a newspaper would use as a nav label, with a one-sentence description. "
    "Return ONLY JSON: {\"name\": str, \"tagline\": str, \"sections\": [{\"name\": str, \"description\": str}]}."
)

AUTHORS_SYSTEM = (
    "You staff the masthead of an independent trade publication with believable recurring writers. Return ONLY a "
    "JSON array of objects {\"name\", \"role\", \"city\", \"started_at\" (YYYY-MM-DD), \"expertise\" (1-2 of the "
    "given sections), \"bio\"}. Names must be plausible, internationally varied and unique; roles come from the "
    "given list; the bio is exactly this shape: '<Name> is a <role, lower case> at <Publication> covering "
    "<expertise, lower case>. Based in <City>, <First name> has written for <Publication> since <Year>.'"
)


def _seeded(slug: str) -> random.Random:
    return random.Random(int(hashlib.sha256(slug.encode()).hexdigest(), 16) % (2 ** 32))


def deterministic_authors(name: str, sections: list[str], count: int, slug: str, *, tenure: str) -> list[dict[str, Any]]:
    rng = _seeded(slug)
    firsts = FIRST_NAMES[:]
    lasts = LAST_NAMES[:]
    rng.shuffle(firsts)
    rng.shuffle(lasts)
    now = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    used: set[str] = set()
    for i in range(count):
        full = f"{firsts[i % len(firsts)]} {lasts[(i * 7) % len(lasts)]}"
        while full in used:
            full = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        used.add(full)
        role = ROLES[i % len(ROLES)]
        section = sections[i % len(sections)] if sections else "features"
        city = CITIES[(i * 5 + rng.randrange(3)) % len(CITIES)]
        if tenure == "real":
            started = now.strftime("%Y-%m-%d")
        else:
            year = now.year - rng.randrange(3, 12)
            started = f"{year}-{rng.randrange(1, 13):02d}-{rng.randrange(1, 28):02d}"
        first = full.split()[0]
        bio = (f"{full} is a {role.lower()} at {name} covering {section.lower()}. "
               f"Based in {city}, {first} has written for {name} since {started[:4]}.")
        out.append({"slug": publication.slugify(full), "name": full, "role": role, "city": city,
                    "started_at": started, "expertise": [section], "bio": bio})
    return out


def llm_authors(cfg: Config, name: str, tagline: str, sections: list[str], count: int, *, tenure: str) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    rule = ("started_at must be today's date for everyone" if tenure == "real"
            else f"started_at must be between {now.year - 11}-01-01 and {now.year - 3}-12-31, varied")
    user = (f"Publication: {name}\nTagline: {tagline}\nSections: {', '.join(sections)}\nRoles: {', '.join(ROLES)}\n"
            f"Count: {count}\nCities: {', '.join(CITIES)}\nRule: {rule}\nCurrent year: {now.year}")
    data = llm.complete_json(cfg, AUTHORS_SYSTEM, user, tier="cheap", max_tokens=4000)
    authors = []
    for a in data if isinstance(data, list) else data.get("authors", []):
        if not isinstance(a, dict) or not a.get("name"):
            continue
        authors.append({
            "slug": publication.slugify(str(a["name"])), "name": str(a["name"]),
            "role": str(a.get("role") or ROLES[len(authors) % len(ROLES)]), "city": str(a.get("city") or ""),
            "started_at": str(a.get("started_at") or now.strftime("%Y-%m-%d")),
            "expertise": [str(x) for x in (a.get("expertise") or [])][:2], "bio": str(a.get("bio") or ""),
        })
    return authors[:count]


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
    tagline = tagline or f"An independent publication on {args.direction or name.lower()}."
    if not args.tagline and not args.from_domain:
        notes.append("tagline defaulted — pass --tagline for a real one-sentence masthead description")
    section_names = [s["name"] for s in sections]
    if llm_ok and not args.deterministic_authors:
        try:
            authors = llm_authors(cfg, name, tagline, section_names, args.authors, tenure=args.author_tenure)
            if len(authors) < max(2, args.authors // 2):
                raise llm.LlmError("too few authors returned")
            notes.append("authors generated by LLM")
        except Exception as exc:  # noqa: BLE001 — deterministic bank is always a valid fallback
            notes.append(f"LLM author generation failed ({http_util.sanitize_text(str(exc))[:120]}); used the deterministic bank")
            authors = deterministic_authors(name, section_names, args.authors, slug, tenure=args.author_tenure)
    else:
        authors = deterministic_authors(name, section_names, args.authors, slug, tenure=args.author_tenure)
    site = {
        "name": name, "slug": slug, "tagline": tagline, "site_url": args.site_url.rstrip("/"),
        "language": args.language, "theme": _pick_theme(slug, args.theme), "icon": args.icon,
        "established": datetime.now(timezone.utc).year,
        "sections": [{"slug": publication.slugify(s["name"]), "name": s["name"], "description": s.get("description", "")}
                     for s in sections],
        "authors": authors,
        "disclosure": {"enabled": bool(args.disclosure),
                       "text": "An independent publication supported by {client}."},
        "client": {"name": client_name, "domain": (args.client_domain or args.from_domain or "").replace("https://", "").rstrip("/")},
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
    parser.add_argument("--authors", type=int, default=DEFAULT_AUTHOR_COUNT, help="Recurring authors to generate (default 8)")
    parser.add_argument("--author-tenure", choices=["backdated", "real"], default="backdated",
                        help="backdated (default, mirrors Letterstory) or real (started_at = today)")
    parser.add_argument("--deterministic-authors", action="store_true", help="Skip the LLM and use the seeded name bank")
    parser.add_argument("--theme", help=f"One of: {', '.join(sorted(publication.THEMES))} (default: seeded pick)")
    parser.add_argument("--icon", default="spark", choices=sorted(publication.ICONS), help="Logo mark")
    parser.add_argument("--language", default="en")
    parser.add_argument("--disclosure", action="store_true", help="Turn the /about disclosure line on (default off)")
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
