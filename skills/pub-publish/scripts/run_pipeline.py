"""pub-publish: one article end to end — the vendor's create_phantom_from_topic
(publication-playbook §4): research -> write -> enhance -> diagrams -> cover
-> (shred) -> publish -> relink -> build. Each step is a sibling skill script
run as a subprocess with its JSON captured; the run stops at the first
failing step and reports where.

Approval posture is respected: with planner.approval_mode manual the run
stops after `cover` unless --approve is given (the draft is then ready for a
human); autopilot runs through.

Usage:
    python3 run_pipeline.py --publication llm-billboard --next                 # next due queued slot
    python3 run_pipeline.py --publication llm-billboard --slug advertiser-readiness --approve
    python3 run_pipeline.py --publication llm-billboard --slug advertiser-readiness --skip shred,cover --dry-run
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
import subprocess  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Any  # noqa: E402

from scripts.lib import publication, pubstate  # noqa: E402

SKILLS_DIR = Path(__file__).resolve().parents[2]
STEPS = ["research", "write", "enhance", "diagrams", "cover", "shred", "publish", "relink", "build"]
DEFAULT_SKIP = {"shred"}


def step_command(step: str, publication_slug: str, slug: str, args: argparse.Namespace) -> list[str]:
    extra = ["--publications-dir", args.publications_dir] if args.publications_dir else []
    common = ["--publication", publication_slug, *extra]
    table = {
        "research": [SKILLS_DIR / "pub-research/scripts/research_outline.py", *common, "--slug", slug],
        "write": [SKILLS_DIR / "pub-write/scripts/write_article.py", *common, "--slug", slug, "--candidates", str(args.candidates)],
        "enhance": [SKILLS_DIR / "pub-enhance/scripts/enhance_article.py", *common, "--slug", slug],
        "diagrams": [SKILLS_DIR / "pub-visuals/scripts/render_diagram.py", *common, "--slug", slug],
        "cover": [SKILLS_DIR / "pub-visuals/scripts/gen_cover.py", *common, "--slug", slug],
        "shred": [SKILLS_DIR / "pub-write/scripts/shred.py", *common, "--slug", slug],
        "publish": [SKILLS_DIR / "pub-publish/scripts/publish_article.py", *common, "--slug", slug] + (["--approve"] if args.approve else []) + (["--indexnow"] if args.indexnow else []),
        "relink": [SKILLS_DIR / "pub-enhance/scripts/relink.py", *common, "--new-slug", slug],
        "build": [SKILLS_DIR / "pub-site/scripts/build_site.py", *common],
    }
    return [sys.executable, *[str(x) for x in table[step]]]


def run_step(cmd: list[str], repo_root: Path) -> dict[str, Any]:
    import os

    env = {**os.environ, "SEO_REPO_ROOT": str(repo_root)}
    env.setdefault("SEO_ENGINE_ROOT", str(_find_engine_root(Path(__file__).resolve())))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, env=env)
    try:
        payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {"stdout": proc.stdout[-800:]}
    return {"exit": proc.returncode, "result": payload, "stderr": proc.stderr[-800:] if proc.returncode else ""}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the article pipeline for one draft.")
    parser.add_argument("--publication", help="Publication slug")
    parser.add_argument("--slug", help="Draft slug")
    parser.add_argument("--next", action="store_true", help="Pick the next due queued planner slot")
    parser.add_argument("--skip", default=",".join(sorted(DEFAULT_SKIP)), help=f"Steps to skip (default {','.join(sorted(DEFAULT_SKIP))}); choose from {STEPS}")
    parser.add_argument("--candidates", type=int, default=2, help="Writer candidates per section")
    parser.add_argument("--approve", action="store_true", help="Human approval to publish (manual/review_window modes)")
    parser.add_argument("--indexnow", action="store_true", help="Pass --indexnow to publish")
    parser.add_argument("--dry-run", action="store_true", help="Print the commands without running them")
    parser.add_argument("--publications-dir", help="Override the publications directory")
    args = parser.parse_args()

    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    root = publication.find_publication(cfg, args.publication)
    pub = publication.load_publication(root)
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    unknown = skip - set(STEPS)
    if unknown:
        parser.error(f"unknown steps in --skip: {sorted(unknown)}")

    slug = args.slug
    slot = None
    if args.next:
        planner = pubstate.load_json(pubstate.state_path(cfg, "planner", root.name), {"slots": []})
        now = datetime.now(timezone.utc).isoformat()
        due = [s for s in planner.get("slots", []) if s.get("status") == "queued" and s.get("scheduled_for", "") <= now and s.get("draft_slug")]
        if not due:
            print(json.dumps({"checked": True, "ran": False, "reason": "no queued slot is due (planner.py --materialize --queue, or wait)"}, indent=2))
            return 0
        slot = sorted(due, key=lambda s: s["scheduled_for"])[0]
        slug = slot["draft_slug"]
    if not slug:
        parser.error("pass --slug or --next")
    approval_mode = str((pub.site.get("planner") or {}).get("approval_mode") or "manual")
    steps = [s for s in STEPS if s not in skip]
    if approval_mode != "autopilot" and not args.approve:
        steps = [s for s in steps if s not in ("publish", "relink", "build")]
    plan = [{"step": s, "cmd": step_command(s, root.name, slug, args)} for s in steps]
    result: dict[str, Any] = {"checked": True, "publication": root.name, "slug": slug, "slot": (slot or {}).get("id"),
                              "approval_mode": approval_mode, "steps": [], "dry_run": args.dry_run}
    if args.dry_run:
        result["plan"] = [{"step": p["step"], "cmd": " ".join(p["cmd"])} for p in plan]
        print(json.dumps(result, indent=2))
        return 0
    for p in plan:
        out = run_step(p["cmd"], cfg.repo_root)
        entry = {"step": p["step"], "exit": out["exit"], "summary": {k: v for k, v in out["result"].items() if k in
                 ("status", "words", "sources_read", "claims_verified", "claims_dropped", "published", "url", "cover", "verify", "changes", "error", "gate", "approval")}}
        if out["exit"] != 0:
            entry["stderr"] = out["stderr"]
            entry["result"] = out["result"]
        result["steps"].append(entry)
        if out["exit"] != 0 and p["step"] not in ("shred",):
            result["stopped_at"] = p["step"]
            break
    if "stopped_at" not in result and approval_mode != "autopilot" and not args.approve:
        result["awaiting_approval"] = f"draft ready in drafts/{slug}.md — rerun with --approve (or set planner.approval_mode autopilot) to publish"
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if "stopped_at" in result else 0


if __name__ == "__main__":
    sys.exit(main())
