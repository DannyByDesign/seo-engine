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
from scripts.lib import config as config_module  # noqa: E402

import argparse  # noqa: E402
import json  # noqa: E402
from typing import Any  # noqa: E402

from scripts.lib import publication  # noqa: E402


def build_one(root: Path, out: Path | None, include_drafts: bool) -> dict[str, Any]:
    pub = publication.load_publication(root, include_drafts=include_drafts)
    manifest = publication.build_site(pub, out)
    manifest.update({"publication": root.name, "site_url": pub.site_url, "sections": len(pub.sections),
                     "authors": len(pub.authors)})
    return manifest


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
    print(json.dumps({"checked": True, "builds": results}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
