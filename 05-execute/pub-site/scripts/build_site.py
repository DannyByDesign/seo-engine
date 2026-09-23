"""pub-site: render a publication into a deployable static site.

Reads <publications_dir>/<slug>/{site.yml, posts/*.md, assets/, static/}
and writes dist/ (see scripts/lib/publication.py for what is rendered and
why). Drafts (status: draft, or no published_at) are skipped unless
--include-drafts is passed for a local preview.

Deploy the dist/ directory as a static site (Vercel: `vercel deploy
dist/ --prod`; the generated vercel.json enables clean URLs). Nothing here
touches the network.

Usage:
    python3 build_site.py --publication llm-billboard
    python3 build_site.py --all
    python3 build_site.py --publication llm-billboard --include-drafts --out /tmp/preview
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
import importlib.util
import tempfile
import fcntl
from typing import Any

from scripts.lib import publication, pubstate


def _render_one(root: Path, out: Path | None, include_drafts: bool) -> dict[str, Any]:
    pub = publication.load_publication(root, include_drafts=include_drafts)
    from scripts.lib import editorial
    invalid = [p.slug for p in pub.posts if not editorial.valid_review(p.meta, p.body_md, root)]
    if invalid and not include_drafts:
        return {'publication': root.name, 'deployed': False, 'validation': {'errors': len(invalid),
                'findings': [{'severity': 'error', 'check': 'stale-editorial-review', 'post': slug} for slug in invalid]}}

    if include_drafts and out is None:
        out = root / 'preview'
    manifest = publication.build_site(pub, out)
    manifest['preview_only'] = include_drafts
    spec = importlib.util.spec_from_file_location("site_validator", Path(__file__).with_name("validate_site.py"))
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    pages, feeds, count = validator.pages_from_dist(Path(manifest["out_dir"]), pub.site_url)
    ctx = {"min_words": 1200, "site_url": pub.site_url, "site_host": pub.host,
           "sibling_hosts": set(), "disclosure_enabled": bool(pub.disclosure), "disclosure_text": pub.disclosure or ""}
    findings = validator.Findings()
    for page in pages:
        if page["kind"] == "other":
            continue
        soup, nodes = validator.check_common(page, ctx, findings)
        if page["kind"] == "post":
            validator.check_post(page, soup, nodes, ctx, findings)
    validator.check_feeds(feeds, count, pub.site_url, findings)
    manifest["validation"] = {"errors": findings.count("error"), "findings": findings.items}
    manifest.update({"publication": root.name, "site_url": pub.site_url, "sections": len(pub.sections),
                     "authors": len(pub.authors)})
    if include_drafts:
        for page in Path(manifest['out_dir']).rglob('*.html'):
            text = page.read_text().replace('<head>', '<head><meta name="robots" content="noindex,nofollow">')
            page.write_text(text)
        (Path(manifest['out_dir']) / 'robots.txt').write_text('User-agent: *\nDisallow: /\n')
    return manifest


def build_one(root: Path, out: Path | None, include_drafts: bool) -> dict[str, Any]:
    target = (out or root / ('preview' if include_drafts else 'dist')).resolve()
    root = root.resolve()
    protected = [root, *(root / name for name in ('posts','drafts','assets','static'))]
    if any(target == p or p.is_relative_to(target) or (p != root and target.is_relative_to(p)) for p in protected):
        raise ValueError('build output cannot replace publication source or an ancestor')
    if include_drafts and target == root / 'dist':
        raise ValueError('preview cannot replace production dist')
    if target.exists() and target not in (root/'dist', root/'preview') and not (target/'.seo-engine-build').is_file():
        raise ValueError('custom output must be new or a previously managed build directory')
    target.parent.mkdir(parents=True, exist_ok=True)
    with (root / '.build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with tempfile.TemporaryDirectory(prefix='.seo-build-', dir=target.parent) as temporary:
            staging = Path(temporary) / 'output'
            try:
                manifest = _render_one(root, staging, include_drafts)
                if manifest['validation']['errors'] and not include_drafts:
                    manifest['last_good_preserved'] = True
                    return manifest
                (staging/'.seo-engine-build').write_text(root.name)
                backup = Path(temporary) / 'previous'
                if target.exists(): target.rename(backup)
                try: staging.rename(target)
                except BaseException:
                    if backup.exists(): backup.rename(target)
                    raise
                manifest['out_dir'] = str(target)
                return manifest
            except Exception as exc:
                return {'publication': root.name, 'last_good_preserved': True,
                        'validation': {'errors': 1, 'findings': [{'severity': 'error', 'check': 'build-failure', 'message': str(exc)[:300]}]}}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a publication's static site into dist/.")
    parser.add_argument("--publication", help="Publication slug (directory name under publications/)")
    parser.add_argument("--all", action="store_true", help="Build every publication")
    parser.add_argument("--out", help="Output directory (default: <publication>/dist)")
    parser.add_argument("--include-drafts", action="store_true", help="Render drafts too (local preview only)")
    parser.add_argument("--publications-dir", help="Override the publications directory")
    args = parser.parse_args()

    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    if args.all and args.out:
        parser.error("--out cannot be combined with --all")

    roots = publication.list_publications(cfg) if args.all else [publication.find_publication(cfg, args.publication)]
    if not roots:
        print(json.dumps({"checked": False, "error": f"no publications under {publication.publications_root(cfg)}",
                          "next_step": "run scaffold_publication.py first"}, indent=2))
        return 1
    results = [build_one(r, Path(args.out) if args.out else None, args.include_drafts) for r in roots]
    for root, result in zip(roots, results):
        if result["validation"]["errors"] or args.include_drafts:
            continue
        path = pubstate.state_path(cfg, "planner", root.name)
        planner = pubstate.load_json(path, {"slots": []})
        for slot in planner.get("slots", []):
            if slot.get("status") == "building" and (root / "posts" / f"{slot.get('draft_slug')}.md").is_file():
                slot["status"] = "published"
                slot["built_at"] = pubstate.now_iso()
        pubstate.save_json(path, planner)
    print(json.dumps({"checked": True, "builds": results, "deployed": False}, indent=2, ensure_ascii=False))
    return 1 if any(r["validation"]["errors"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
