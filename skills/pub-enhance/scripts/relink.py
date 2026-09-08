"""pub-enhance: retro-link the back catalogue to a newly published post — the
`relink` pass measured on live phantoms (13 of 44 internal links pointed at
posts published later; dateModified moved when they were added).

For each older post (newest first, up to --max-posts), find the paragraph
with the strongest term overlap with the new post whose text contains a
phrase from the new post's title, insert one link (at most --max-per-post),
and bump `updated_at` ONLY if the body changed — never touch a date without
a change (red-flags §3, §7). Rebuild the site afterwards (pub-site).

Usage:
    python3 relink.py --publication llm-billboard                       # link older posts to the newest post
    python3 relink.py --publication llm-billboard --new-slug advertiser-readiness --max-posts 8 --dry-run
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

from scripts.lib import article, publication, pubstate  # noqa: E402

MIN_OVERLAP = 0.10


def relink_post(old: publication.Post, new: publication.Post, max_per_post: int) -> tuple[str, list[dict[str, Any]]]:
    if f"](/posts/{new.slug})" in old.body_md:
        return old.body_md, []
    items = article.blocks(old.body_md)
    target_text = f"{new.title} {new.dek} {' '.join(article.headings(new.body_md))}"
    ranked = sorted(((pubstate.overlap(b["text"], target_text), i) for i, b in enumerate(items) if b["kind"] == "para"), reverse=True)
    inserted = []
    for score, i in ranked:
        if score < MIN_OVERLAP or len(inserted) >= max_per_post:
            break
        phrase = article.find_anchor_phrase(items[i]["text"], new.title)
        if not phrase:
            continue
        new_text, changed = article.insert_link(items[i]["text"], phrase, f"/posts/{new.slug}")
        if changed:
            items[i]["text"] = new_text
            inserted.append({"anchor": phrase, "overlap": round(score, 3)})
    return (article.join_blocks(items) if inserted else old.body_md), inserted


def main() -> int:
    parser = argparse.ArgumentParser(description="Link older posts to a newly published post.")
    parser.add_argument("--publication", help="Publication slug")
    parser.add_argument("--new-slug", help="The new post (default: newest published)")
    parser.add_argument("--max-per-post", type=int, default=1, help="Links to insert per older post (default 1)")
    parser.add_argument("--max-posts", type=int, default=6, help="Older posts to consider, newest first (default 6)")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    parser.add_argument("--publications-dir", help="Override the publications directory")
    args = parser.parse_args()

    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    root = publication.find_publication(cfg, args.publication)
    pub = publication.load_publication(root)
    if not pub.posts:
        print(json.dumps({"checked": False, "error": "no published posts"}, indent=2))
        return 1
    new = next((p for p in pub.posts if p.slug == args.new_slug), None) if args.new_slug else pub.posts[0]
    if new is None:
        print(json.dumps({"checked": False, "error": f"no published post {args.new_slug!r}"}, indent=2))
        return 1
    changes = []
    for old in [p for p in pub.posts if p.slug != new.slug][: args.max_posts]:
        body, inserted = relink_post(old, new, args.max_per_post)
        if not inserted:
            continue
        entry = {"post": old.slug, "inserted": inserted, "updated_at_bumped": False}
        if not args.dry_run and old.path is not None:
            old.meta["updated_at"] = pubstate.now_iso()
            publication.write_post(old.path, old.meta, body)
            entry["updated_at_bumped"] = True
        changes.append(entry)
    print(json.dumps({"checked": True, "publication": root.name, "new_post": new.slug, "dry_run": args.dry_run,
                      "posts_considered": min(len(pub.posts) - 1, args.max_posts), "changes": changes,
                      "next_step": "rebuild the site (pub-site build_site.py) so the new links and dateModified go live" if changes else None},
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
