"""pub-publish: promote a draft to a published post — the one place the
quality gate and the approval posture are enforced.

Gate (skip individual checks only with --skip-checks, never silently):
  * body present, research done, enhanced_at present, cover present
  * optional --min-words and --min-sources policies (defaults 0), current contribution permission
  * no client link unless mention.allowed
  * approval: planner.approval_mode manual -> needs --approve;
    review_window -> written_at older than the window or --approve;
    autopilot -> proceeds
Then: published_at is set ONCE (now, or --at), updated_at = published_at,
status published, the file moves drafts/ -> posts/, the topic-map spoke is
marked covered, the suggestion and planner slot are marked published, and
optional hooks run: --relink (pub-enhance), --build (pub-site), --indexnow.

Usage:
    python3 publish_article.py --publication llm-billboard --slug advertiser-readiness --approve --relink --build
    python3 publish_article.py --publication llm-billboard --slug advertiser-readiness --at 2026-09-09T20:15:00Z --approve
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
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from scripts.lib import article, editorial, indexnow, publication, pubstate
from scripts.lib.config import Config

from scripts.lib.paths import skill


def gate(meta: dict[str, Any], body: str, strategy: dict[str, Any], *, min_words: int, min_sources: int) -> list[str]:
    problems = []
    if not body.strip():
        problems.append("empty body")
    if (meta.get("research") or {}).get("status") != "done":
        problems.append("research not done")
    if not meta.get("enhanced_at"):
        problems.append("not enhanced (run pub-enhance)")
    if not (isinstance(meta.get("cover"), dict) and meta["cover"].get("src")):
        problems.append("no cover (follow pub-visuals to source the planned image or generate an illustration)")
    words = article.word_count(body)
    min_words, min_sources = max(0, min_words), max(0, min_sources)
    if words < min_words:
        problems.append(f"{words} words < {min_words}")
    if len({s.get("url") for s in meta.get("sources", []) if isinstance(s, dict) and s.get("url")}) < min_sources:
        problems.append(f"{len(meta.get('sources') or [])} sources < {min_sources}")
    if (meta.get("verification") or {}).get("unverified"):
        problems.append("unverified numbers remain")
    if len(set(body.lower().split())) < min(10, max(1, words // 10)):
        problems.append("repetitive content")
    host = str((strategy.get("client") or {}).get("domain") or "").lower().removeprefix("www.")
    if host:
        client_links = [u for _, u in article.links_in(body) if urlparse(u).hostname and (urlparse(u).hostname.lower() == host or urlparse(u).hostname.lower().endswith("." + host))]
        if client_links and not (isinstance(meta.get("mention"), dict) and meta["mention"].get("allowed")):
            problems.append("client link present but mention not allowed")
        if len(client_links) > 1:
            problems.append("more than one client link")
    return problems


def approval(conf: dict[str, Any], meta: dict[str, Any], approve: bool) -> tuple[bool, str]:
    mode = str(conf.get("approval_mode") or "manual")
    if approve or mode == "autopilot":
        return True, mode
    if mode == "review_window":
        written = publication.parse_iso((meta.get("editorial_review") or {}).get("reviewed_at"))
        hours = float(conf.get("review_window_hours") or 24)
        if written and datetime.now(timezone.utc) - written >= timedelta(hours=hours):
            return True, f"review_window elapsed ({hours}h)"
        return False, f"review window of {hours}h has not elapsed — pass --approve to publish now"
    return False, "approval_mode is manual — pass --approve"


def run_hook(cfg: Config, script: Path, args: list[str]) -> dict[str, Any]:
    import os

    env = {**os.environ, "SEO_REPO_ROOT": str(cfg.repo_root)}
    env.setdefault("SEO_ENGINE_ROOT", str(_find_engine_root(Path(__file__).resolve())))
    proc = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, timeout=600, env=env)
    try:
        payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {"stdout": proc.stdout[-500:]}
    return {"script": script.name, "exit": proc.returncode, "result": payload, "stderr": proc.stderr[-500:] if proc.returncode else ""}


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a draft: gate, approve, move, mark, hooks.")
    parser.add_argument("--publication", help="Publication slug")
    parser.add_argument("--slug", required=True, help="Draft slug")
    parser.add_argument("--at", help="published_at ISO timestamp (default now)")
    parser.add_argument("--approve", action="store_true", help="Human approval for manual/review_window modes")
    parser.add_argument("--min-words", type=int, default=0, help="Optional publication-specific length floor; editorial review always required")
    parser.add_argument("--min-sources", type=int, default=0, help="Optional public-source count; interview evidence is assessed in editorial review")
    parser.add_argument("--skip-checks", action="store_true", help="Publish despite gate failures (logged in frontmatter)")
    parser.add_argument("--relink", action="store_true", help="Run pub-enhance relink.py afterwards")
    parser.add_argument("--build", action="store_true", help="Run pub-site build_site.py afterwards")
    parser.add_argument("--indexnow", action="store_true", help="Submit the new URL via IndexNow when configured")
    parser.add_argument("--publications-dir", help="Override the publications directory")
    args = parser.parse_args()

    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    root = publication.find_publication(cfg, args.publication)
    pub = publication.load_publication(root)
    strategy = pubstate.load_strategy(root)
    draft = root / "drafts" / f"{args.slug}.md"
    if not draft.is_file():
        print(json.dumps({"checked": False, "error": f"{draft} not found"}, indent=2))
        return 1
    meta, body = publication.read_post(draft)
    problems = gate(meta, body, strategy, min_words=args.min_words, min_sources=args.min_sources)
    from scripts.lib import content
    try:
        content.check_article(meta, root, args.slug, cfg.repo_root)
    except ValueError as exc:
        print(json.dumps({'checked': False, 'published': False, 'error': str(exc), 'gate': problems + [str(exc)]}))
        return 1
    if not editorial.valid_review(meta, body, root):
        print(json.dumps({"checked": True, "published": False, "gate": problems + ["missing or stale editorial review"],
                          "approval": "run review_article.py on the final prepared draft"}))
        return 1
    cover = root / "assets" / publication.asset_name(meta, args.slug) / str((meta.get("cover") or {}).get("src") or "")
    if not cover.is_file():
        problems.append("cover asset missing")
    if (pub.site.get("client") or {}).get("name") and not pub.disclosure:
        print(json.dumps({"published": False, "gate": ["owned publication must disclose its publisher"]}))
        return 1
    conf = dict(pub.site.get("planner") or {})
    ok, why = approval(conf, meta, args.approve)
    if (problems and not args.skip_checks) or not ok:
        print(json.dumps({"checked": True, "published": False, "gate": problems, "approval": why,
                          "hint": "fix the gate items, or --skip-checks to override (recorded); pass --approve when a human has reviewed"}, indent=2))
        return 1

    when = args.at or pubstate.now_iso()
    original_published = meta.get("original_published_at") if meta.get("refresh_of") else None
    if publication.parse_iso(when) is None:
        parser.error("--at must be an ISO timestamp")
    meta.update({"status": "published", "slug": args.slug, "published_at": original_published or meta.get("published_at") or when,
                 "updated_at": when})
    if problems:
        meta["gate_overridden"] = problems
    if meta.get("original_author"):
        meta["author"] = meta["original_author"]
    if not meta.get("author"):
        authors = list(pub.authors.values())
        if authors:
            counts = {a["slug"]: 0 for a in authors}
            for p in pub.posts:
                counts[pub.author_for(p)["slug"]] = counts.get(pub.author_for(p)["slug"], 0) + 1
            meta["author"] = min(authors, key=lambda a: counts.get(a["slug"], 0))["slug"]
    target = root / "posts" / f"{args.slug}.md"
    if target.exists() and meta.get("refresh_of") != args.slug:
        print(json.dumps({"checked": False, "error": "post already exists; queue an explicit refresh"}))
        return 1
    publication.write_post(target, meta, body)
    draft.unlink()

    topic_map = pubstate.load_topic_map(root)
    spoke = pubstate.find_spoke(topic_map, str(meta.get("spoke_id") or ""))
    if spoke is not None:
        spoke.update({"status": "covered", "article_slug": args.slug, "covered_at": pubstate.now_iso()})
        pubstate.save_topic_map(root, topic_map)
    sugg_path = pubstate.state_path(cfg, "suggestions", root.name)
    suggestions = pubstate.load_json(sugg_path, {"items": []})
    for item in suggestions.get("items", []):
        if item.get("draft_slug") == args.slug:
            item["status"] = "published"
    pubstate.save_json(sugg_path, suggestions)
    planner_path = pubstate.state_path(cfg, "planner", root.name)
    planner = pubstate.load_json(planner_path, {"slots": []})
    for slot in planner.get("slots", []):
        if slot.get("draft_slug") == args.slug:
            slot.update({"status": "building", "published_at": meta["published_at"]})
    pubstate.save_json(planner_path, planner)

    url = pub.url(f"/posts/{args.slug}")
    result: dict[str, Any] = {"checked": True, "published": True, "file": str(target), "url": url, "published_at": meta["published_at"],
                              "author": meta.get("author"), "gate_overridden": problems if problems else [], "approval": why, "hooks": []}
    extra = ["--publications-dir", args.publications_dir] if args.publications_dir else []
    if args.relink:
        result["hooks"].append(run_hook(cfg, skill('pub-enhance') / "scripts" / "relink.py", ["--publication", root.name, "--new-slug", args.slug, *extra]))
    if args.build:
        result["hooks"].append(run_hook(cfg, skill('pub-site') / "scripts" / "build_site.py", ["--publication", root.name, *extra]))
    if args.indexnow:
        if cfg.integration_available("indexnow"):
            try:
                status = indexnow.submit(cfg, [url, pub.url("/sitemap.xml")])
                result["hooks"].append({"script": "indexnow", "status": status})
            except Exception as exc:
                result["hooks"].append({"script": "indexnow", "error": str(exc)[:200]})
        else:
            result["hooks"].append({"script": "indexnow", "skipped": "INDEXNOW_API_KEY not set (Bing feeds ChatGPT — geo-playbook §10)"})
    result["next_steps"] = [s for s in [
        None if args.relink else "run pub-enhance relink.py so older posts link here",
        None if args.build else "rebuild with pub-site build_site.py and deploy dist/",
        "run pub-curate build_topic_map.py --mark-covered (done for this spoke) and score_suggestions.py to refill the queue",
    ] if s]
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if any(h.get("exit", 0) != 0 or h.get("error") for h in result["hooks"]) else 0


if __name__ == "__main__":
    sys.exit(main())
