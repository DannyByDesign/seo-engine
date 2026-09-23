"""pub-site: validate a built (or live) publication against the anatomy
checklist in ../seo-references/publication-playbook.md §2-§3.

Three input modes:
  --publication <slug>   validate <publication>/dist (default when one publication exists)
  --html-dir <dir>       validate saved HTML files (each treated as an article unless the
                         filename says home/section/author/about) — how the fixture test
                         checks the validator against a real Letterstory page
  --url <site url>       fetch the live site: home, robots, sitemap, feeds and a sample of
                         posts/sections/authors (bounded by --max-pages)

What it checks, per page: <html lang>, theme tokens, robots/googlebot meta, canonical
(absolute, and equal to the page URL in dist mode), OG/Twitter, the Organization+WebSite
JSON-LD graph, page-kind JSON-LD (BlogPosting+BreadcrumbList / Blog / ProfilePage /
AboutPage / CollectionPage), single H1, body H2 count and the TOC, inline-citation nofollow
vs followed Sources, `citation[]` mirroring the Sources list, image alt + dimensions, word
count, at least one internal body link. Site-wide: feed/llms.txt/sitemap parse and agree
with the post count, sitemap priorities, robots.txt allows citation-relevant AI crawlers
(RFC 9309 evaluation via scripts/lib/robots.py — blocking a training-only bot is a warning,
blocking a citation bot is an error), no links to sibling publications or to the vendor,
and the /about disclosure line matches site.yml.

Severity: error = breaks the anatomy or discoverability; warning = a measured
best-practice missed; info = advisory. Exit 1 on any error (or any warning with --strict).

Usage:
    python3 validate_site.py --publication llm-billboard
    python3 validate_site.py --html-dir ./saved-pages
    python3 validate_site.py --url https://llmbillboard.com --max-pages 6
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
from scripts.lib import config as config_module

import argparse
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from scripts.lib import http_util, publication, robots

CITATION_CRAWLERS = ["Googlebot", "Bingbot", "OAI-SearchBot", "ChatGPT-User", "Claude-SearchBot", "Claude-User",
                     "PerplexityBot", "Perplexity-User", "Applebot", "Amazonbot"]
TRAINING_CRAWLERS = ["GPTBot", "ClaudeBot", "Google-Extended", "CCBot", "Bytespider", "Meta-ExternalAgent",
                     "Applebot-Extended"]
VENDOR_HOSTS = ("letterstory.com", "phantomstory.com", "letterbrace.com", "lettertrace.com")
DEFAULT_MIN_WORDS = 1200
LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


class Findings:
    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def add(self, severity: str, page: str, check: str, message: str) -> None:
        self.items.append({"severity": severity, "page": page, "check": check, "message": message})

    def error(self, page: str, check: str, message: str) -> None:
        self.add("error", page, check, message)

    def warn(self, page: str, check: str, message: str) -> None:
        self.add("warning", page, check, message)

    def info(self, page: str, check: str, message: str) -> None:
        self.add("info", page, check, message)

    def count(self, severity: str) -> int:
        return sum(1 for f in self.items if f["severity"] == severity)


def kind_of(url_path: str) -> str:
    p = url_path.strip("/")
    if p in ("", "index.html"):
        return "home"
    head = p.split("/")[0]
    return {"posts": "post", "sections": "section", "authors": "author", "about": "about",
            "search": "search", "404.html": "notfound"}.get(head, "other")


def ld_nodes(html: str, page: str, findings: Findings) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for raw in LD_RE.findall(html):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            findings.error(page, "jsonld-parse", "JSON-LD block does not parse")
            continue
        for item in (data if isinstance(data, list) else [data]):
            if not isinstance(item, dict):
                continue
            if "@graph" in item:
                nodes.extend(n for n in item["@graph"] if isinstance(n, dict))
            else:
                nodes.append(item)
    return nodes


def _types(nodes: list[dict[str, Any]]) -> list[str]:
    return [str(n.get("@type")) for n in nodes]


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def check_common(page: dict[str, Any], ctx: dict[str, Any], findings: Findings) -> tuple[BeautifulSoup, list[dict[str, Any]]]:
    name, html = page["url_path"], page["html"]
    soup = BeautifulSoup(html, "lxml")
    root = soup.find("html")
    if root is None or not root.get("lang"):
        findings.error(name, "html-lang", "<html lang> missing")
    if root is not None and not root.get("data-theme"):
        findings.warn(name, "theme-tokens", "<html data-theme> missing (theme tokens on the root element)")
    robots_meta = soup.find("meta", attrs={"name": "robots"})
    robots_value = (robots_meta.get("content") if robots_meta else "") or ""
    if page["kind"] in ("search", "notfound"):
        if "noindex" not in robots_value:
            findings.warn(name, "robots-meta", "search/404 pages should be noindex")
    else:
        if "noindex" in robots_value:
            findings.error(name, "robots-meta", "page is noindex")
        elif "index" not in robots_value:
            findings.warn(name, "robots-meta", "meta robots 'index, follow' missing")
        gb = soup.find("meta", attrs={"name": "googlebot"})
        if not gb or "max-image-preview:large" not in (gb.get("content") or ""):
            findings.warn(name, "googlebot-meta", "meta googlebot with max-image-preview:large missing")
        canonical = soup.find("link", attrs={"rel": lambda v: v and "canonical" in v})
        href = (canonical.get("href") if canonical else "") or ""
        if not href:
            findings.error(name, "canonical", "canonical link missing")
        elif not urlparse(href).scheme:
            findings.error(name, "canonical", f"canonical is not absolute: {href}")
        elif ctx.get("site_url") and page.get("expected_url") and href.rstrip("/") != page["expected_url"].rstrip("/"):
            findings.error(name, "canonical", f"canonical {href} != page URL {page['expected_url']}")
        if not ctx.get("site_host") and href:
            ctx["site_host"] = _host(href)
        for prop in ("og:title", "og:description", "og:url", "og:type"):
            if not soup.find("meta", attrs={"property": prop}):
                findings.warn(name, "open-graph", f"{prop} missing")
        if not soup.find("meta", attrs={"name": "twitter:card"}):
            findings.warn(name, "twitter-card", "twitter:card missing")
    nodes = ld_nodes(html, name, findings)
    types = _types(nodes)
    if page["kind"] not in ("notfound",):
        if "Organization" not in types or "WebSite" not in types:
            findings.error(name, "jsonld-graph", f"Organization+WebSite graph missing (found {types})")
    return soup, nodes


def check_post(page: dict[str, Any], soup: BeautifulSoup, nodes: list[dict[str, Any]], ctx: dict[str, Any], findings: Findings) -> None:
    name = page["url_path"]
    types = _types(nodes)
    og_type = soup.find("meta", attrs={"property": "og:type"})
    if og_type and (og_type.get("content") or "") != "article":
        findings.warn(name, "open-graph", "og:type should be 'article' on a post")
    bp = next((n for n in nodes if n.get("@type") in ("BlogPosting", "Article", "NewsArticle")), None)
    if bp is None:
        findings.error(name, "jsonld-article", f"BlogPosting missing (found {types})")
    else:
        for key in ("headline", "datePublished", "dateModified", "author", "publisher", "image"):
            if not bp.get(key):
                findings.warn(name, "jsonld-article", f"BlogPosting.{key} missing")
        author = bp.get("author")
        if isinstance(author, dict) and not author.get("name"):
            findings.warn(name, "jsonld-article", "BlogPosting.author.name missing")
    if "BreadcrumbList" not in types:
        findings.warn(name, "jsonld-breadcrumb", "BreadcrumbList missing")

    article = soup.find("article") or soup.find("main") or soup
    h1s = soup.find_all("h1")
    if len(h1s) != 1:
        findings.error(name, "h1", f"expected exactly one <h1>, found {len(h1s)}")
    body_h2 = [h for h in article.find_all("h2") if h.get("id") and h.get("id") != "sources-heading"]
    if len(body_h2) < 4:
        findings.warn(name, "structure", f"only {len(body_h2)} body H2 sections with ids (measured norm 6-8)")
    if len(body_h2) >= 3 and "In this article" not in article.get_text(" "):
        findings.warn(name, "toc", "'In this article' table of contents missing")

    sources_heading = next((h for h in article.find_all(["h2", "h3"]) if h.get_text(strip=True).lower() == "sources"), None)
    sources_block = sources_heading.find_parent(["section", "div", "aside"]) if sources_heading else None
    source_links: list = []
    if sources_heading is not None:
        container = sources_block or sources_heading.find_next_sibling(["ol", "ul"])
        if container is not None:
            source_links = [a for a in container.find_all("a", href=True) if urlparse(a["href"]).scheme]
        for a in source_links:
            if "nofollow" in (a.get("rel") or []):
                findings.warn(name, "sources-followed", "Sources list links should be followed (no nofollow)")
                break
        if bp is not None:
            citations = bp.get("citation") or []
            if len(citations) != len(source_links):
                findings.warn(name, "citation-mirror", f"citation[] has {len(citations)} entries, Sources list has {len(source_links)}")

    site_host = ctx.get("site_host") or ""
    inline_external = []
    internal_body = 0
    for a in article.find_all("a", href=True):
        if source_links and a in source_links:
            continue
        href = a["href"]
        parsed = urlparse(href)
        if parsed.scheme in ("http", "https"):
            host = _host(href)
            if site_host and (host == site_host or host.endswith("." + site_host)):
                if "/posts/" in parsed.path:
                    internal_body += 1
                continue
            if any(s in href for s in ("twitter.com/intent", "facebook.com/sharer", "linkedin.com/sharing")):
                continue
            inline_external.append(a)
        elif href.startswith("/posts/"):
            internal_body += 1
    missing_nofollow = [a["href"] for a in inline_external if "nofollow" not in (a.get("rel") or [])]
    if missing_nofollow:
        findings.warn(name, "inline-nofollow", f"{len(missing_nofollow)} inline external link(s) without nofollow, e.g. {missing_nofollow[0]}")
    if internal_body == 0:
        findings.warn(name, "internal-links", "no internal links to other posts in the body")
    for host in {_host(a["href"]) for a in inline_external}:
        ctx.setdefault("external_hosts", set()).add(host)

    for img in article.find_all("img"):
        if not img.has_attr('alt'):
            findings.error(name, "img-alt", f"image without alt text: {img.get('src', '')[:80]}")
        if not (img.get("width") and img.get("height")):
            findings.warn(name, "img-dimensions", f"image without width/height: {img.get('src', '')[:80]}")
    if not soup.find("meta", attrs={"property": "og:image"}):
        findings.warn(name, "cover", "no og:image / cover")

    prose = article.find(class_="prose") or article
    words = len(prose.get_text(" ", strip=True).split())
    if words < ctx["min_words"]:
        findings.warn(name, "length", f"{words} words in the article (floor {ctx['min_words']})")


def check_kind(page: dict[str, Any], nodes: list[dict[str, Any]], findings: Findings) -> None:
    name, kind, types = page["url_path"], page["kind"], _types(nodes)
    if kind == "home" and "Blog" not in types:
        findings.warn(name, "jsonld-blog", "Blog JSON-LD with blogPost[] missing on the home page")
    if kind == "author" and "ProfilePage" not in types:
        findings.warn(name, "jsonld-profile", "ProfilePage JSON-LD missing on the author page")
    if kind == "about" and "AboutPage" not in types:
        findings.warn(name, "jsonld-about", "AboutPage JSON-LD missing")
    if kind == "section" and "CollectionPage" not in types:
        findings.info(name, "jsonld-collection", "CollectionPage JSON-LD missing on the section page (optional)")


def check_feeds(feeds: dict[str, Optional[str]], post_count: Optional[int], site_url: str, findings: Findings) -> None:
    robots_txt = feeds.get("robots.txt")
    if robots_txt is None:
        findings.error("/robots.txt", "robots", "robots.txt missing")
    else:
        policy = robots.parse(robots_txt)
        probe = (site_url or "https://example.invalid") + "/posts/example"
        for ua in CITATION_CRAWLERS:
            if not policy.allowed(ua, probe):
                findings.error("/robots.txt", "ai-crawlers", f"{ua} is blocked — it gates search/AI-answer citation")
        for ua in TRAINING_CRAWLERS:
            if not policy.allowed(ua, probe):
                findings.warn("/robots.txt", "ai-crawlers", f"{ua} is blocked (training-only; the measured sites allow all crawlers)")
        if "sitemap:" not in robots_txt.lower():
            findings.warn("/robots.txt", "robots", "no Sitemap: line")
    sitemap = feeds.get("sitemap.xml")
    if sitemap is None:
        findings.error("/sitemap.xml", "sitemap", "sitemap.xml missing")
    else:
        try:
            root = ET.fromstring(sitemap.encode("utf-8"))
        except ET.ParseError:
            root = None
            findings.error("/sitemap.xml", "sitemap", "sitemap.xml does not parse")
        if root is not None:
            def local(tag: str) -> str:
                return tag.rsplit("}", 1)[-1]
            urls = [u for u in root if local(u.tag) == "url"]
            locs = [c.text for u in urls for c in u if local(c.tag) == "loc"]
            priorities = {c.text for u in urls for c in u if local(c.tag) == "priority"}
            lastmods = [c.text for u in urls for c in u if local(c.tag) == "lastmod"]
            if not urls:
                findings.error("/sitemap.xml", "sitemap", "sitemap has no <url> entries")
            if not priorities & {"1", "1.0"}:
                findings.warn("/sitemap.xml", "sitemap-priority", "home page priority 1.0 missing")
            if "0.7" not in priorities:
                findings.warn("/sitemap.xml", "sitemap-priority", "posts priority 0.7 missing")
            if len(lastmods) < len(urls):
                findings.warn("/sitemap.xml", "sitemap-lastmod", f"{len(urls) - len(lastmods)} url(s) without lastmod")
            posts_in_sitemap = sum(1 for l in locs if l and "/posts/" in l)
            if post_count is not None and posts_in_sitemap != post_count:
                findings.warn("/sitemap.xml", "sitemap-coverage", f"sitemap lists {posts_in_sitemap} posts, site has {post_count}")
    feed = feeds.get("feed.xml")
    if feed is None:
        findings.warn("/feed.xml", "rss", "feed.xml missing")
    else:
        try:
            items = ET.fromstring(feed.encode("utf-8")).findall(".//item")
            if post_count is not None and len(items) != min(post_count, publication.RSS_LIMIT):
                findings.warn("/feed.xml", "rss", f"feed has {len(items)} items, site has {post_count} posts")
        except ET.ParseError:
            findings.error("/feed.xml", "rss", "feed.xml does not parse")
    llms = feeds.get("llms.txt")
    if llms is None:
        findings.warn("/llms.txt", "llms-txt", "llms.txt missing (the measured sites ship one; it is not a citation lever — geo-playbook §1)")
    else:
        lines = [l for l in llms.splitlines() if l.startswith("- [")]
        if "## Posts" not in llms:
            findings.warn("/llms.txt", "llms-txt", "llms.txt lacks a '## Posts' section")
        if post_count is not None and len(lines) != post_count:
            findings.warn("/llms.txt", "llms-txt", f"llms.txt lists {len(lines)} posts, site has {post_count}")


def check_network(ctx: dict[str, Any], pages: list[dict[str, Any]], findings: Findings) -> None:
    hosts = ctx.get("external_hosts", set())
    for page in pages:
        soup = BeautifulSoup(page["html"], "lxml")
        for a in soup.find_all("a", href=True):
            if urlparse(a["href"]).scheme in ("http", "https"):
                hosts.add(_host(a["href"]))
    for host in sorted(hosts):
        if host in ctx.get("sibling_hosts", set()):
            findings.error("site", "network-footprint", f"links to sibling publication {host} — publications must never interlink")
        if any(host == v or host.endswith("." + v) for v in VENDOR_HOSTS):
            findings.error("site", "network-footprint", f"links to the vendor domain {host}")
    about = next((p for p in pages if p["kind"] == "about"), None)
    if about is not None and ctx.get("disclosure_enabled") is not None:
        text = BeautifulSoup(about["html"], "lxml").get_text(" ")
        wanted = ctx.get("disclosure_text") or ""
        if ctx["disclosure_enabled"] and wanted and wanted not in text:
            findings.error("/about", "disclosure", "site.yml enables disclosure but /about does not carry the line")
        if not ctx["disclosure_enabled"] and "supported by" in text.lower():
            findings.info("/about", "disclosure", "disclosure is off in site.yml but /about mentions support")


def pages_from_dist(dist: Path, site_url: str) -> tuple[list[dict[str, Any]], dict[str, Optional[str]], int]:
    pages = []
    for path in sorted(dist.rglob("*.html")):
        rel = path.relative_to(dist).as_posix()
        url_path = "/" if rel == "index.html" else "/" + rel.removesuffix("/index.html").removesuffix(".html")
        pages.append({"url_path": url_path, "kind": kind_of(url_path), "html": path.read_text(encoding="utf-8"),
                      "expected_url": site_url if url_path == "/" else site_url + url_path})
    feeds = {n: ((dist / n).read_text(encoding="utf-8") if (dist / n).is_file() else None)
             for n in ("robots.txt", "sitemap.xml", "feed.xml", "llms.txt")}
    return pages, feeds, sum(1 for p in pages if p["kind"] == "post")


def pages_from_html_dir(directory: Path) -> tuple[list[dict[str, Any]], dict[str, Optional[str]]]:
    pages = []
    for path in sorted(directory.glob("*.html")):
        stem = path.stem.lower()
        kind = next((k for k in ("home", "section", "author", "about", "search") if k in stem), "post")
        pages.append({"url_path": "/" + path.name, "kind": kind, "html": path.read_text(encoding="utf-8"), "expected_url": None})
    feeds = {n: ((directory / n).read_text(encoding="utf-8") if (directory / n).is_file() else None)
             for n in ("robots.txt", "sitemap.xml", "feed.xml", "llms.txt")}
    return pages, feeds


def pages_from_url(site_url: str, max_pages: int) -> tuple[list[dict[str, Any]], dict[str, Optional[str]], Optional[int]]:
    def fetch(url: str) -> Optional[str]:
        try:
            resp = http_util.get(url, timeout=30.0)
            return resp.text if resp.status_code == 200 else None
        except Exception:
            return None

    feeds = {n: fetch(urljoin(site_url + "/", n)) for n in ("robots.txt", "sitemap.xml", "feed.xml", "llms.txt")}
    locs: list[str] = []
    if feeds["sitemap.xml"]:
        try:
            root = ET.fromstring(feeds["sitemap.xml"].encode("utf-8"))
            locs = [c.text for u in root for c in u if c.tag.rsplit("}", 1)[-1] == "loc" and c.text]
        except ET.ParseError:
            pass
    post_urls = [l for l in locs if "/posts/" in l]
    picks = [site_url + "/"] + post_urls[:max_pages]
    for pattern in ("/sections/", "/authors/"):
        first = next((l for l in locs if pattern in l), None)
        if first:
            picks.append(first)
    picks.append(site_url + "/about")
    pages = []
    for url in picks:
        html = fetch(url)
        if html is None:
            continue
        path = urlparse(url).path or "/"
        pages.append({"url_path": path, "kind": kind_of(path), "html": html, "expected_url": url.rstrip("/") or site_url})
    return pages, feeds, (len(post_urls) if locs else None)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a publication against the anatomy checklist.")
    parser.add_argument("--publication", help="Publication slug (validates its dist/)")
    parser.add_argument("--dist", help="Explicit dist directory to validate")
    parser.add_argument("--html-dir", help="Directory of saved HTML pages to validate")
    parser.add_argument("--url", help="Live site URL to fetch and validate")
    parser.add_argument("--max-pages", type=int, default=5, help="Posts to sample in --url mode (default 5)")
    parser.add_argument("--min-words", type=int, default=DEFAULT_MIN_WORDS, help=f"Article word floor (default {DEFAULT_MIN_WORDS})")
    parser.add_argument("--strict", action="store_true", help="Exit 1 on warnings too")
    parser.add_argument("--publications-dir", help="Override the publications directory")
    args = parser.parse_args()

    findings = Findings()
    ctx: dict[str, Any] = {"min_words": args.min_words, "site_host": "", "site_url": "", "sibling_hosts": set(),
                           "disclosure_enabled": None, "disclosure_text": ""}
    cfg = None
    try:
        cfg = config_module.load()
        if args.publications_dir:
            cfg.site["publications_dir"] = args.publications_dir
    except Exception:
        cfg = None

    post_count: Optional[int] = None
    mode = "dist"
    if args.html_dir:
        mode = "html-dir"
        pages, feeds = pages_from_html_dir(Path(args.html_dir))
    elif args.url:
        mode = "url"
        ctx["site_url"] = args.url.rstrip("/")
        ctx["site_host"] = _host(args.url)
        pages, feeds, post_count = pages_from_url(ctx["site_url"], args.max_pages)
    else:
        if cfg is None:
            parser.error("--publication/--dist need a repo with .seo-engine (or use --html-dir / --url)")
        root = Path(args.dist).parent if args.dist else publication.find_publication(cfg, args.publication)
        dist = Path(args.dist) if args.dist else root / "dist"
        if not dist.is_dir():
            print(json.dumps({"checked": False, "error": f"{dist} does not exist — run build_site.py first"}, indent=2))
            return 1
        site_yml = root / "site.yml"
        if site_yml.is_file():
            pub = publication.load_publication(root)
            ctx.update({"site_url": pub.site_url, "site_host": pub.host,
                        "disclosure_enabled": bool(pub.disclosure), "disclosure_text": pub.disclosure or ""})
            ctx["sibling_hosts"] = {_host(str(p.get("site_url"))) for p in (cfg.site.get("publications") or [])
                                    if isinstance(p, dict) and p.get("site_url") and p.get("slug") != root.name}
        pages, feeds, post_count = pages_from_dist(dist, ctx["site_url"])

    if not pages:
        print(json.dumps({"checked": False, "error": "no pages found to validate"}, indent=2))
        return 1
    for page in pages:
        if page["kind"] == "other":
            continue
        soup, nodes = check_common(page, ctx, findings)
        if page["kind"] == "post":
            check_post(page, soup, nodes, ctx, findings)
        else:
            check_kind(page, nodes, findings)
    if mode != "html-dir" or any(feeds.values()):
        check_feeds(feeds, post_count, ctx.get("site_url") or "", findings)
    check_network(ctx, pages, findings)

    errors, warnings = findings.count("error"), findings.count("warning")
    report = {
        "checked": True, "mode": mode, "pages_checked": len(pages), "posts_checked": sum(1 for p in pages if p["kind"] == "post"),
        "summary": {"errors": errors, "warnings": warnings, "info": findings.count("info")},
        "findings": findings.items,
        "verdict": "fail" if errors or (args.strict and warnings) else "pass",
    }
    if cfg is not None:
        try:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            out = cfg.reports_dir / f"pub-site-validate-{stamp}.json"
            out.write_text(json.dumps(report, indent=2), encoding="utf-8")
            report["report_file"] = str(out)
        except Exception:
            pass
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report["verdict"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
