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
import hashlib  # noqa: E402
import importlib.util  # noqa: E402
import subprocess  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Any  # noqa: E402

from scripts.lib import publication, pubstate  # noqa: E402

from scripts.lib.paths import skill
STEPS = ["research", "write", "enhance", "diagrams", "cover", "shred", "publish", "relink", "build"]
DEFAULT_SKIP = {"shred"}


def step_command(step: str, publication_slug: str, slug: str, args: argparse.Namespace) -> list[str]:
    extra = ["--publications-dir", args.publications_dir] if args.publications_dir else []
    common = ["--publication", publication_slug, *extra]
    table = {
        "research": [skill('pub-research') / 'scripts/research_outline.py', *common, "--slug", slug],
        "write": [skill('pub-write') / 'scripts/write_article.py', *common, "--slug", slug, "--candidates", str(args.candidates)],
        "enhance": [skill('pub-enhance') / 'scripts/enhance_article.py', *common, "--slug", slug, "--strict-verify"],
        "diagrams": [skill('pub-visuals') / 'scripts/render_diagram.py', *common, "--slug", slug],
        "cover": [skill('pub-visuals') / 'scripts/gen_cover.py', *common, "--slug", slug],
        "shred": [skill('pub-write') / 'scripts/shred.py', *common, "--slug", slug],
        "publish": [skill('pub-publish') / 'scripts/publish_article.py', *common, "--slug", slug] + (["--approve"] if args.approve else []) + (["--indexnow"] if args.indexnow else []),
        "relink": [skill('pub-enhance') / 'scripts/relink.py', *common, "--new-slug", slug],
        "build": [skill('pub-site') / 'scripts/build_site.py', *common],
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
        now = datetime.now(timezone.utc)
        due = [s for s in planner.get("slots", []) if s.get("status") in ("queued", "building")
               and publication.parse_iso(s.get("scheduled_for")) is not None
               and publication.parse_iso(s["scheduled_for"]) <= now and s.get("draft_slug")]
        if not due:
            print(json.dumps({"checked": True, "ran": False, "reason": "no queued slot is due (planner.py --materialize --queue, or wait)"}, indent=2))
            return 0
        slot = sorted(due, key=lambda s: s["scheduled_for"])[0]
        slug = slot["draft_slug"]
    if not slug:
        parser.error("pass --slug or --next")
    approval_mode = str((pub.site.get("planner") or {}).get("approval_mode") or "manual")
    draft_path = root / "drafts" / f"{slug}.md"
    post_path = root / "posts" / f"{slug}.md"
    meta, body = publication.read_post(draft_path) if draft_path.is_file() else ({}, "")
    spec = importlib.util.spec_from_file_location("publish_gate", skill('pub-publish') / 'scripts/publish_article.py')
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    can_publish, _ = publisher.approval(pub.site.get("planner") or {}, meta, args.approve)
    steps = [s for s in STEPS if s not in skip]
    if post_path.is_file() and not draft_path.is_file():
        can_publish = True  # recovery only; content is already published locally
        steps = [s for s in steps if s in ("relink", "build")]
    elif args.approve and not body.strip():
        print(json.dumps({"checked": False, "error": "prepare and review a draft before --approve"}))
        return 1
    elif body.strip():
        steps = [s for s in steps if s not in ("research", "write")]
        # Prepared drafts stay immutable while awaiting approval. Edits invalidate
        # the preparation fingerprint and require preparing/reviewing again.
        ready_path = pubstate.state_path(cfg, "prepared", root.name + "-" + slug)
        prepared = pubstate.load_json(ready_path, {})
        digest = hashlib.sha256(draft_path.read_bytes()).hexdigest()
        if prepared.get("sha256") == digest:
            steps = [s for s in steps if s in ("publish", "relink", "build")]
        elif args.approve:
            print(json.dumps({"checked": False, "error": "draft changed after preparation; run without --approve and review again"}))
            return 1
    elif (meta.get("research") or {}).get("status") == "done":
        steps = [s for s in steps if s != "research"]
    if draft_path.is_file():
        from scripts.lib import editorial
        if editorial.valid_review(meta, body, root):
            steps = [s for s in steps if s in ("publish", "relink", "build")]
        else:
            can_publish = False
    if not can_publish:
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
                 ("status", "words", "sources_read", "claims_verified", "claims_dropped", "published", "url", "cover", "verify", "changes", "error", "gate", "approval", "languagetool")}}
        if out["exit"] != 0:
            entry["stderr"] = out["stderr"]
            entry["result"] = out["result"]
        result["steps"].append(entry)
        if out["exit"] != 0 and p["step"] not in ("shred",):
            result["stopped_at"] = p["step"]
            break
    if "stopped_at" not in result and not can_publish:
        if draft_path.is_file() and not args.dry_run:
            pubstate.save_json(pubstate.state_path(cfg, "prepared", root.name + "-" + slug),
                               {"sha256": hashlib.sha256(draft_path.read_bytes()).hexdigest(), "at": pubstate.now_iso()})
        result["awaiting_approval"] = f"draft ready in drafts/{slug}.md — record review with review_article.py, then rerun with --approve; unattended modes also require an unchanged reviewed draft"
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if "stopped_at" in result else 0


if __name__ == "__main__":
    sys.exit(main())
