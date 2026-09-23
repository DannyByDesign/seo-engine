"""Generate an IndexNow key and scaffold its verification file into the
site's STATIC-SOURCE directory (the one deployed verbatim to the site root).

Target-dir resolution, strictest first:
  1. --dir (explicit path wins)
  2. `static_source_dir` from .seo-engine/config.yml (recorded by seo-setup
     from detect_stack.py's `suggested_config`)
  3. neither -> structured `static_source_unknown` refusal (run seo-setup
     first) — this script never guesses a directory.

It REFUSES to write into the framework's build-output directory (e.g.
Hugo's public/, SvelteKit's build/) unless --allow-build-output: build
output is wiped on every build, so a key file there silently disappears —
the exact failure mode that makes IndexNow submissions start 403ing weeks
later with no visible cause.

Key-file reuse: IndexNow verifies that {key}.txt *contains* the key, so an
existing file is only reusable when file content == filename stem. A
mismatch is a structured error, never silent reuse.
"""

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
from typing import Optional

from scripts.lib import indexnow, snapshots


def _fail(result: dict, error_type: str, message: str) -> None:
    result.update({"error_type": error_type, "error": message})
    json.dump(result, sys.stdout, indent=2)
    print()
    sys.exit(1)


def _find_reusable_key_file(target_dir: Path) -> Optional[Path]:
    """A *.txt file in the target dir whose content equals its stem — an
    already-valid IndexNow verification file."""
    for candidate in sorted(target_dir.glob("*.txt")):
        try:
            content = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if content and content == candidate.stem and 8 <= len(content) <= 128:
            return candidate
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an IndexNow key and scaffold its verification file into the "
                    "site's static-source directory (never the build output)."
    )
    parser.add_argument(
        "--dir", default=None,
        help="Directory whose contents deploy verbatim to the site root (e.g. public/ for "
             "Next.js, static/ for Hugo/SvelteKit). Defaults to static_source_dir from "
             ".seo-engine/config.yml (written by seo-setup); refuses to guess when neither "
             "is available.",
    )
    parser.add_argument(
        "--existing-key-file", default=None,
        help="Path to an already-generated {key}.txt file. Reused ONLY if its content equals "
             "its filename stem (IndexNow verifies content, not just the name).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Generate and write a brand-new key even if a reusable key file exists. Only do "
             "this if you intend to update INDEXNOW_API_KEY everywhere it's set.",
    )
    parser.add_argument(
        "--allow-build-output", action="store_true",
        help="Override the refusal to write into the detected build-output directory. Almost "
             "always wrong — build output is wiped on every build.",
    )
    args = parser.parse_args()

    cfg = config_module.load()
    result: dict = {}

    configured_static = str(cfg.site.get("static_source_dir") or "").strip()
    configured_build = str(cfg.site.get("build_output_dir") or "").strip()

    if args.dir:
        target_dir = Path(args.dir).resolve()
        result["dir_source"] = "--dir flag"
    elif configured_static:
        target_dir = (cfg.repo_root / configured_static).resolve()
        result["dir_source"] = "static_source_dir from .seo-engine/config.yml"
    else:
        _fail(result, "static_source_unknown", (
            "No --dir given and no static_source_dir in .seo-engine/config.yml. "
            "Run the seo-setup skill first (detect_stack.py reports the framework's "
            "static-source vs build-output dirs and seo-setup records them) — this "
            "script refuses to guess, because writing the key file into a build-output "
            "directory silently loses it on the next build."
        ))

    result["target_dir"] = str(target_dir)

    if configured_build:
        build_dir = (cfg.repo_root / configured_build).resolve()
        if target_dir == build_dir and not args.allow_build_output:
            _fail(result, "refused_build_output_dir", (
                f"{target_dir} is the detected BUILD OUTPUT directory "
                f"('{configured_build}'), which is wiped/regenerated on every build — a "
                "key file there disappears silently (e.g. public/ is Hugo's build "
                "output; its static-source dir is static/). Use the static-source dir, "
                "or pass --allow-build-output if you are certain this deployment keeps "
                "the file."
            ))

    if not target_dir.is_dir():
        _fail(result, "dir_not_found", (
            f"{target_dir} is not an existing directory. Create it first, or fix "
            "static_source_dir in .seo-engine/config.yml (see seo-setup)."
        ))

    if not args.force:
        candidates = []
        if args.existing_key_file:
            candidates.append(Path(args.existing_key_file))
        scanned = _find_reusable_key_file(target_dir)
        if scanned is not None:
            candidates.append(scanned)

        for existing_path in candidates:
            if not existing_path.is_file():
                result.setdefault("notes_pre_generation", []).append(
                    f"--existing-key-file {existing_path} does not exist — ignoring."
                )
                continue
            content = existing_path.read_text(encoding="utf-8").strip()
            if content != existing_path.stem:
                _fail(result, "key_file_content_mismatch", (
                    f"{existing_path} contains {content[:40]!r}, which does not equal its "
                    f"filename stem {existing_path.stem!r}. IndexNow verifies the file's "
                    "CONTENT — this file would fail verification. Fix the file (content "
                    "must equal the key/filename) or generate a fresh key with --force."
                ))
            result.update({
                "reused_existing_key": True,
                "key_file": str(existing_path),
                "key": content,
                "env_var_line": f"INDEXNOW_API_KEY={content}",
                "notes": (
                    "Found a valid existing key file (content matches filename) and reused "
                    "it instead of generating a new one (pass --force to rotate). Confirm "
                    "INDEXNOW_API_KEY in .env matches this key."
                ),
            })
            json.dump(result, sys.stdout, indent=2)
            print()
            snapshots.prune(cfg)
            return

    key = indexnow.generate_key()
    written_path = indexnow.write_key_file(target_dir, key)

    result.update({
        "reused_existing_key": False,
        "key_file": str(written_path),
        "key": key,
        "env_var_line": f"INDEXNOW_API_KEY={key}",
        "verification_url_after_deploy": (
            "https://{your-domain}/" + written_path.name
            + "  (replace {your-domain} with the site's actual host; this must resolve once "
            "deployed for IndexNow to trust submissions using this key)"
        ),
        "next_steps": [
            f"Set INDEXNOW_API_KEY={key} in .env at the repo root.",
            f"Commit {written_path.name} (inside {target_dir}) so it ships with the next deploy "
            "-- it's a public, harmless verification token, not a secret, safe to commit.",
            "After deploying, confirm the file is reachable at https://{host}/" + written_path.name
            + " before relying on IndexNow submissions.",
            "Run sync_indexing.py with --changed-url/--changed-urls-file to submit changed "
            "URLs once the key is live.",
        ],
        "scope_reminder": (
            "This key only works for IndexNow participants (Bing, Yandex, Naver, Seznam.cz, Yep, "
            "Amazon, and Yahoo per Bing's own materials) -- Google and Baidu do not participate. "
            "For Google, rely on sitemaps + GSC URL Inspection (see sync_indexing.py), never "
            "IndexNow. GEO note: Bing's index is what ChatGPT search retrieves against "
            "(geo-playbook.md §10), so prompt IndexNow submission is an AI-visibility action too."
        ),
    })

    json.dump(result, sys.stdout, indent=2)
    print()
    snapshots.prune(cfg)


if __name__ == "__main__":
    main()
