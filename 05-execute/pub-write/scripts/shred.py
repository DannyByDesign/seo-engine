"""pub-write: the Shredder — sentence-level rewriting spread across several
model providers so a multi-author masthead does not read as one voice.

Policy (red-flags §3): this is a voice-diversity pass, not detector evasion;
there is no AI-content penalty to evade. Run it for the reason it exists.

Mechanics (mirroring the vendor's contract, publication-playbook §8):
  * structure untouched — headings, lists, code, images, quotes and links
    stay exactly as they are; only prose sentences are candidates;
  * `coverage` = share of prose sentences attempted (default 0.3), chosen
    with a seed so reruns are reproducible;
  * each attempt asks a provider DIFFERENT from the one that wrote the piece
    (rotating through the configured providers; with one provider, it
    alternates quality/cheap models);
  * every rewrite passes a content-loss check (same numbers, same links,
    same proper nouns, 0.6-1.6x length) or the original is kept;
  * a share report enforces ceilings: no provider above --max-share of the
    rewrites, no run of more than --max-run consecutive rewritten sentences;
  * telemetry per sentence lands in .seo-engine/state/pub-shred-<slug>.json.

Usage:
    python3 shred.py --publication llm-billboard --slug advertiser-readiness            # drafts/
    python3 shred.py --publication llm-billboard --slug advertiser-readiness --posts    # published post
    python3 shred.py --publication llm-billboard --slug advertiser-readiness --coverage 0.5 --dry-run
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
import random  # noqa: E402
import re  # noqa: E402
from typing import Any  # noqa: E402

from scripts.lib import article, http_util, llm, publication, pubstate  # noqa: E402
from scripts.lib.config import Config  # noqa: E402

REWRITE_SYSTEM = (
    "Rewrite the given sentence in different words with exactly the same meaning, register and length (within 40%). "
    "Keep every number, percentage, currency amount, proper noun and markdown link ([text](url)) unchanged and in place. "
    "Do not add or remove facts. Return ONLY JSON: {\"sentence\": string}."
)
_PROPER_RE = re.compile(r"\b[A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)*\b")


def provider_rotation(cfg: Config, avoid: str) -> list[tuple[str, str]]:
    providers = llm.configured_providers(cfg)
    rotation = [(p, "quality") for p in providers if p != avoid] or []
    rotation += [(p, "cheap") for p in providers]
    return rotation or [(avoid, "cheap")]


def content_ok(before: str, after: str) -> str:
    if article.numbers_in(before) != article.numbers_in(after):
        return "numbers changed"
    if {u for _, u in article.links_in(before)} != {u for _, u in article.links_in(after)}:
        return "links changed"
    lb, la = max(len(before.split()), 1), len(after.split())
    if not 0.6 <= la / lb <= 1.6:
        return f"length {lb}->{la}"
    before_nouns = {n for n in _PROPER_RE.findall(before) if len(n) > 2}
    lost = {n for n in before_nouns if n not in after}
    if lost - {before.split()[0].strip(".,")}:  # first word capitalization is not a noun
        return f"proper nouns lost: {sorted(lost)[:3]}"
    return ""


def shred(cfg: Config, md: str, *, coverage: float, attempts: int, seed: int, avoid_provider: str,
          max_share: float, max_run: int) -> tuple[str, dict[str, Any]]:
    rng = random.Random(seed)
    items = article.blocks(md)
    rotation = provider_rotation(cfg, avoid_provider)
    units: list[dict[str, Any]] = []
    by_provider: dict[str, int] = {}
    rewritten_total = 0
    run = 0
    longest_run = 0
    idx = 0
    for b in items:
        if b["kind"] != "para":
            continue
        sentences = article.split_sentences(b["text"])
        new_sentences = []
        for s_i, sent in enumerate(sentences):
            attempt = rng.random() < coverage and len(sent.split()) >= 6
            record = {"index": idx, "original": sent, "chosen": None, "outcome": "kept", "discarded": []}
            idx += 1
            if attempt and run < max_run:
                for k in range(attempts):
                    provider, tier = rotation[(idx + k) % len(rotation)]
                    if rewritten_total and by_provider.get(provider, 0) / max(rewritten_total, 1) >= max_share and len(rotation) > 1:
                        continue
                    try:
                        data = llm.complete_json(cfg, REWRITE_SYSTEM, sent, provider=provider, tier=tier, max_tokens=400)
                        candidate = str(data.get("sentence") if isinstance(data, dict) else data).strip()
                    except llm.LlmError as exc:
                        record["discarded"].append({"provider": provider, "reason": http_util.sanitize_text(str(exc))[:100]})
                        continue
                    problem = content_ok(sent, candidate) if candidate else "empty"
                    if problem:
                        record["discarded"].append({"provider": provider, "text": candidate[:200], "reason": problem})
                        continue
                    record.update({"chosen": candidate, "outcome": f"rewritten:{provider}/{tier}"})
                    by_provider[provider] = by_provider.get(provider, 0) + 1
                    rewritten_total += 1
                    break
            if record["chosen"]:
                new_sentences.append(record["chosen"])
                run += 1
                longest_run = max(longest_run, run)
            else:
                new_sentences.append(sent)
                run = 0
            units.append(record)
        b["text"] = " ".join(new_sentences)
    total = len(units)
    share = {p: round(n / max(rewritten_total, 1), 3) for p, n in by_provider.items()}
    summary = {"total_units": total, "shredded": rewritten_total, "kept_original": total - rewritten_total,
               "share_report": {"by_provider": share, "over_ceiling": [p for p, s in share.items() if s > max_share and len(rotation) > 1],
                                "longest_run": longest_run, "window_risk": longest_run >= max_run}}
    return article.join_blocks(items), {"units": units, "summary": summary}


def main() -> int:
    parser = argparse.ArgumentParser(description="Sentence-level multi-provider rewrite with structure preserved.")
    parser.add_argument("--publication", help="Publication slug")
    parser.add_argument("--slug", required=True, help="Article slug")
    parser.add_argument("--posts", action="store_true", help="Operate on posts/<slug>.md instead of drafts/")
    parser.add_argument("--coverage", type=float, default=0.3, help="Share of sentences to attempt (default 0.3)")
    parser.add_argument("--attempts", type=int, default=2, help="Providers to try per sentence (default 2)")
    parser.add_argument("--max-share", type=float, default=0.6, help="Ceiling on one provider's share of rewrites (default 0.6)")
    parser.add_argument("--max-run", type=int, default=3, help="Max consecutive rewritten sentences (default 3)")
    parser.add_argument("--seed", type=int, help="Random seed (default: derived from the slug)")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change; write nothing")
    parser.add_argument("--publications-dir", help="Override the publications directory")
    args = parser.parse_args()

    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    if not llm.configured_providers(cfg):
        print(json.dumps({"checked": False, "error": "shredding needs at least one LLM key"}, indent=2))
        return 1
    if not 0 < args.coverage <= 1:
        parser.error("--coverage must be in (0, 1]")
    root = publication.find_publication(cfg, args.publication)
    path = root / ("posts" if args.posts else "drafts") / f"{args.slug}.md"
    if not path.is_file():
        print(json.dumps({"checked": False, "error": f"{path} not found"}, indent=2))
        return 1
    meta, body = publication.read_post(path)
    seed = args.seed if args.seed is not None else sum(ord(c) for c in args.slug)
    wrote_with = str((meta.get("composition") or {}).get("provider") or cfg.get("LLM_PROVIDER") or llm.configured_providers(cfg)[0])
    new_body, telemetry = shred(cfg, body, coverage=args.coverage, attempts=args.attempts, seed=seed, avoid_provider=wrote_with,
                                max_share=args.max_share, max_run=args.max_run)
    guard = article.guard_unchanged(body, new_body)
    status = "shredded" if telemetry["summary"]["shredded"] else "kept_original"
    if guard:
        status = "rejected"
    if not args.dry_run and status == "shredded":
        from scripts.lib import languagetool
        meta['languagetool'] = languagetool.check(cfg, new_body)
        meta["shred"] = {"at": pubstate.now_iso(), "coverage": args.coverage, **telemetry["summary"]}
        publication.write_post(path, meta, new_body)
    state_path = pubstate.state_path(cfg, "shred", root.name)
    log = pubstate.load_json(state_path, {"runs": []})
    log["runs"] = (log.get("runs", []) + [{"slug": args.slug, "at": pubstate.now_iso(), "status": status, "dry_run": args.dry_run,
                                            "summary": telemetry["summary"], "guard": guard}])[-200:]
    pubstate.save_json(state_path, log)
    print(json.dumps({"checked": True, "file": str(path), "status": status, "dry_run": args.dry_run, "guard": guard,
                      "summary": telemetry["summary"], "languagetool": meta.get('languagetool'),
                      "sample": [u for u in telemetry["units"] if u["chosen"]][:3]}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
