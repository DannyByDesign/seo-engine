"""Record accountable editorial review of a prepared article and its evidence."""

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
import hashlib
import json
from scripts.lib import editorial, publication, pubstate


def main():
    parser = argparse.ArgumentParser(description="Record accountable review of the final prepared article.")
    parser.add_argument("--publication")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--posts", action="store_true", help="Review existing published content during migration")
    parser.add_argument("--review-file", required=True, help="JSON with reviewer, reader_need, value_added, facts_checked, claims")
    parser.add_argument("--publications-dir")
    args = parser.parse_args()
    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    root = publication.find_publication(cfg, args.publication)
    path = root / ("posts" if args.posts else "drafts") / f"{args.slug}.md"
    meta, body = publication.read_post(path)
    review = json.loads(Path(args.review_file).read_text())
    try:
        meta["editorial_review"] = editorial.record_review(meta, body, root, review)
    except ValueError as exc:
        print(json.dumps({"checked": False, "error": str(exc)})); return 1
    publication.write_post(path, meta, body)
    pubstate.save_json(pubstate.state_path(cfg, "prepared", root.name + "-" + args.slug),
                       {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "at": pubstate.now_iso()})
    print(json.dumps({"checked": True, "reviewed": True, "digest": meta["editorial_review"]["digest"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
