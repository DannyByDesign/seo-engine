"""AI-search visibility tracking through OpenRouter with Exa web search.

Measures configured model API samples, not consumer apps. Model/search identities
are separate from historical direct-vendor series.

Measurement honesty (geo-playbook.md section 9): a single LLM probe is a coin
flip, not a measurement. This script therefore takes --samples N (default 3)
probes per prompt x provider and aggregates them into an explicit per-provider
STATE rather than a raw boolean:

  cited          cited in >= ceil(valid_samples / 2) of the non-error samples
  not_cited      cited in 0 non-error samples
  mixed          cited in some samples but short of a majority (intermittent)
  error          every sample for this provider ended in an API error --
                 an UNKNOWN, never to be read as "not cited"
  not_configured provider has no API key set

Pipeline per run:
  1. Resolve the tracked-prompt list (see _resolve_prompts below) and the
     target domain (cfg.site_url's host).
  2. For each prompt, call scripts.lib.ai_visibility.probe_all(cfg, prompt,
     target_domain) N times (--samples) and aggregate per provider into the
     state machine above. probe_all internally skips providers with no key
     and reports per-provider errors as an explicit error state (never as
     cited:false).
  3. If PROFOUND_API_KEY / OTTERLY_API_KEY are configured, also call the
     corresponding commercial-tracker function once per run (not once per
     prompt) and attach the result as a clearly-labeled separate block.
  4. Append one schema-v2 record per prompt per run to
     .seo-engine/state/ai-visibility-history.jsonl (JSON Lines).
  5. Diff each prompt's per-provider STATE against the same prompt's prior
     schema-v2 history records:
       - any pair where the prior or current state is `error` is classified
         `indeterminate_provider_error` -- its own bucket, EXCLUDED from
         gained/lost counts (a transient 429 must never read as "lost all
         citations");
       - gains (-> cited) report immediately as `newly_cited`;
       - losses are flap-damped: the first cited -> not_cited transition
         emits `possible_citation_loss` (severity low, unconfirmed); a loss
         is only promoted to `newly_lost_citations` after 2 CONSECUTIVE
         not_cited runs following a cited run;
       - URL-level citation diffs are computed only between runs where BOTH
         states are `cited`, over the union of target-matching citation URLs
         across samples (`cited_but_different_pages`).
     History records without schema_version (the old single-sample format)
     are not comparable and are ignored with an explicit note.

History schema v2 (one JSONL record per prompt per run):
  {schema_version: 2, run_id, generated_at, prompt, prompt_source,
   target_domain, samples_per_provider,
   providers: {name: {state, cited_count, valid_samples, error_samples,
                      citation_urls, errors}}}

Cost note: one run makes (configured providers) x (prompts) x (--samples)
web-search LLM API calls -- each is a billed web-search/grounding call. The
report includes the exact figure for the run.

Tracked-prompt resolution order (see _resolve_prompts):
  1. `geo_prompts` in .seo-engine/config.yml, if non-empty -- a curated list
     of full natural-language prompts the site owner actually cares about
     (e.g. "what's the best project management tool for a 10-person startup").
  2. Falls back to `target_topics` (already used by seo-rank-tracking) turned
     into a generic "what is the best X" prompt shape -- a usable but weaker
     substitute, clearly labeled as such in the output.
  3. If both are empty, the script does NOT invent prompts or guess at
     plausible ones. It exits with checked=false and an explicit instruction:
     the calling agent should ask the site owner which queries matter and
     write them into .seo-engine/config.yml under geo_prompts, then re-run.
     Guessing prompts here would silently measure the wrong thing.

Usage:
    python3 track_ai_visibility.py                     # 3 samples per prompt x provider
    python3 track_ai_visibility.py --samples 5         # tighter vote, higher API cost
    python3 track_ai_visibility.py --prompt "..." --prompt "..."   # ad hoc prompts
    python3 track_ai_visibility.py --domain example.com            # override target domain
    python3 track_ai_visibility.py --skip-trackers                 # DIY probing only

Output: structured JSON to stdout, one schema-v2 record appended per prompt to
.seo-engine/state/ai-visibility-history.jsonl, and a dated summary report
written to .seo-engine/reports/.
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
import math
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from scripts.lib import ai_visibility, http_util, snapshots, urlnorm
from scripts.lib.config import Config, MissingConfigError

HISTORY_FILENAME = "ai-visibility-history.jsonl"
HISTORY_SCHEMA_VERSION = 2
DEFAULT_SAMPLES = 3

PROVIDER_STATES = ("cited", "not_cited", "mixed", "error", "not_configured")


def _target_domain(cfg: Config, override: Optional[str]) -> str:
    if override:
        return override.strip().lower().removeprefix("www.")
    host = urlparse(cfg.site_url).netloc
    return host.lower().removeprefix("www.")


def _resolve_prompts(cfg: Config, cli_prompts: list[str]) -> tuple[list[str], str, list[str]]:
    """Returns (prompts, source, notes). source is one of "cli", "geo_prompts",
    "target_topics_derived", or "none" -- callers must check for "none" and
    stop rather than proceeding with an empty/guessed list."""
    notes: list[str] = []

    if cli_prompts:
        notes.append(f"Using {len(cli_prompts)} prompt(s) passed via --prompt on the command line.")
        return cli_prompts, "cli", notes

    geo_prompts = [p.strip() for p in (cfg.site.get("geo_prompts") or []) if p and p.strip()]
    if geo_prompts:
        notes.append(
            f"Using {len(geo_prompts)} curated prompt(s) from geo_prompts in "
            ".seo-engine/config.yml."
        )
        return geo_prompts, "geo_prompts", notes

    target_topics = [t.strip() for t in (cfg.site.get("target_topics") or []) if t and t.strip()]
    if target_topics:
        derived = [f"What is the best {topic}?" for topic in target_topics]
        notes.append(
            f"No geo_prompts configured -- derived {len(derived)} generic prompt(s) from "
            "target_topics as a fallback. These are weaker signal than curated prompts: a "
            "real site owner rarely phrases a question exactly as \"what is the best <topic>\". "
            "Recommend the site owner (or a future session) populate geo_prompts in "
            ".seo-engine/config.yml with actual representative queries."
        )
        return derived, "target_topics_derived", notes

    notes.append(
        "No geo_prompts and no target_topics configured in .seo-engine/config.yml, and no "
        "--prompt given on the command line. This skill will not guess plausible prompts -- "
        "measuring AI-search visibility for made-up queries the site owner may not actually "
        "care about would produce a report that looks precise but measures the wrong thing."
    )
    return [], "none", notes


def _load_history(cfg: Config) -> list[dict[str, Any]]:
    path = cfg.state_dir / HISTORY_FILENAME
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _append_history(cfg: Config, records: list[dict[str, Any]]) -> Path:
    path = cfg.state_dir / HISTORY_FILENAME
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
    return path


def _prior_comparable_records(
    history: list[dict[str, Any]], prompt: str, target_domain: str,
    current_run_id: str, limit: int = 2,
) -> list[dict[str, Any]]:
    """The most recent `limit` schema-v2 records for this prompt+domain,
    newest first. Records without schema_version are the old single-sample
    format -- not comparable to multi-sample states, so they are excluded
    (callers surface that via _has_old_format_history)."""
    matches = [
        r for r in history
        if r.get("schema_version") == HISTORY_SCHEMA_VERSION
        and r.get("prompt") == prompt
        and r.get("target_domain") == target_domain
        and r.get("run_id") != current_run_id
    ]
    matches.sort(key=lambda r: r.get("generated_at", ""))
    return matches[-limit:][::-1]


def _has_old_format_history(
    history: list[dict[str, Any]], prompt: str, target_domain: str,
) -> bool:
    return any(
        r.get("schema_version") is None
        and r.get("prompt") == prompt
        and r.get("target_domain") == target_domain
        for r in history
    )


def _host_matches_target(url: str, target_domain: str) -> bool:
    host = urlparse(url).netloc.lower()
    host = host.removeprefix("www.")
    target = target_domain.lower().removeprefix("www.")
    return bool(host) and (host == target or host.endswith("." + target))


def _citation_identity(citation: dict[str, Any], target_domain: str) -> str:
    """Stable identity for a target-matching citation. Prefers the raw URL
    when its host actually matches the target; falls back to the title for
    citations matched via title (Gemini's grounding URIs are opaque
    vertexaisearch redirects that change every run -- diffing them would be
    pure noise)."""
    url = (citation.get("url") or "").strip()
    if url and _host_matches_target(url, target_domain):
        return url
    title = (citation.get("title") or "").strip()
    return title or url


def _aggregate_provider_samples(
    provider_samples: list[dict[str, Any]], target_domain: str,
) -> tuple[dict[str, Any], list[str]]:
    """Fold N probe_all samples for one provider into the state machine.
    Returns (history-record aggregate, per-sample outcome list for the report).

    States: not_configured (no key), error (0 non-error samples), cited
    (majority of non-error samples), not_cited (0 cited samples), mixed
    (cited in some samples but short of a majority). An errored sample is
    excluded from the vote -- error is never conflated with not-cited."""
    if not any(s.get("configured") for s in provider_samples):
        aggregate = {
            "state": "not_configured", "cited_count": 0, "valid_samples": 0,
            "error_samples": 0, "citation_urls": [], "errors": [],
        }
        return aggregate, ["not_configured"] * len(provider_samples)

    cited_count = 0
    valid_samples = 0
    error_samples = 0
    errors: list[dict[str, str]] = []
    seen_errors: set[tuple[str, str]] = set()
    urls_by_key: dict[str, str] = {}
    outcomes: list[str] = []

    for sample in provider_samples:
        if not sample.get("configured"):
            outcomes.append("not_configured")
            continue
        if sample.get("error"):
            error_samples += 1
            outcomes.append("error")
            err_text = http_util.sanitize_text(str(sample.get("error")))
            err_type = str(sample.get("error_type") or "")
            if (err_type, err_text) not in seen_errors:
                seen_errors.add((err_type, err_text))
                errors.append({"error": err_text, "error_type": err_type})
            continue
        valid_samples += 1
        outcomes.append("cited" if sample.get("cited") else "not_cited")
        if sample.get("cited"):
            cited_count += 1
        for citation in sample.get("citations", []):
            if not ai_visibility.citation_matches(citation, target_domain):
                continue
            identity = _citation_identity(citation, target_domain)
            if identity:
                urls_by_key.setdefault(urlnorm.canonical_key(identity), identity)

    if valid_samples == 0:
        state = "error"
    elif cited_count == 0:
        state = "not_cited"
    elif cited_count >= math.ceil(valid_samples / 2):
        state = "cited"
    else:
        state = "mixed"

    aggregate = {
        "state": state,
        "cited_count": cited_count,
        "valid_samples": valid_samples,
        "error_samples": error_samples,
        "citation_urls": sorted(urls_by_key.values()),
        "errors": errors,
    }
    return aggregate, outcomes


def _url_key_map(urls: Optional[list[str]]) -> dict[str, str]:
    """canonical_key -> raw URL. Diff by folded key, display raw."""
    return {urlnorm.canonical_key(u): u for u in (urls or []) if u}


def _diff_against_prior(
    current: dict[str, Any], priors: list[dict[str, Any]], old_format_present: bool,
) -> dict[str, Any]:
    """Per-provider STATE diff against the most recent comparable (schema v2)
    prior record, with flap-damped loss detection using the record before
    that. Error states poison a comparison: any pair where prior or current
    state is `error` is `indeterminate_provider_error`, excluded from
    gained/lost counts."""
    diff: dict[str, Any] = {"has_prior_run": bool(priors)}
    if old_format_present:
        diff["history_note"] = (
            "Pre-v2 history records (single-sample format, no schema_version) exist for "
            "this prompt+domain but are not comparable to multi-sample state records -- "
            "they were ignored. Trend tracking starts fresh from schema v2."
        )
    if not priors:
        if "history_note" not in diff:
            diff["note"] = (
                "No comparable (schema v2) prior run recorded for this prompt+domain -- "
                "nothing to diff yet."
            )
        return diff

    prior1 = priors[0]
    prior2 = priors[1] if len(priors) > 1 else None
    diff["prior_run_id"] = prior1.get("run_id")
    diff["prior_generated_at"] = prior1.get("generated_at")

    per_provider: dict[str, Any] = {}
    for provider in (current.get("providers") or {}):
        cur_p = (current.get("providers") or {}).get(provider) or {}
        prior_p = (prior1.get("providers") or {}).get(provider) or {}
        prior2_p = ((prior2.get("providers") or {}).get(provider) or {}) if prior2 else {}

        cur_state = cur_p.get("state")
        prior_state = prior_p.get("state")
        prior2_state = prior2_p.get("state")

        if cur_state in (None, "not_configured") and prior_state in (None, "not_configured"):
            continue

        entry: dict[str, Any] = {
            "state_now": cur_state,
            "state_before": prior_state,
            "newly_gained_citation_urls": [],
            "newly_lost_citation_urls": [],
        }

        if cur_state == "error" or prior_state == "error":
            entry["change"] = "indeterminate_provider_error"
            entry["note"] = (
                "The current or prior run for this provider ended in an API error state -- "
                "no citation conclusion can be drawn from this pair. A transient 429/5xx "
                "must never be read as a citation loss; this pair is excluded from "
                "gained/lost counts entirely."
            )
        elif prior_state in (None, "not_configured"):
            entry["change"] = "provider_newly_configured"
        elif cur_state == "not_configured":
            entry["change"] = "provider_no_longer_configured"
        elif prior_state == "cited" and cur_state == "cited":
            cur_urls = _url_key_map(cur_p.get("citation_urls"))
            prior_urls = _url_key_map(prior_p.get("citation_urls"))
            gained = [cur_urls[k] for k in sorted(set(cur_urls) - set(prior_urls))]
            lost = [prior_urls[k] for k in sorted(set(prior_urls) - set(cur_urls))]
            entry["newly_gained_citation_urls"] = gained
            entry["newly_lost_citation_urls"] = lost
            entry["change"] = "cited_but_different_pages" if (gained or lost) else "unchanged"
        elif cur_state == "cited":
            entry["change"] = "newly_cited"
            entry["newly_gained_citation_urls"] = sorted(
                _url_key_map(cur_p.get("citation_urls")).values()
            )
        elif prior_state == "cited" and cur_state == "not_cited":
            entry["change"] = "possible_citation_loss"
            entry["last_known_citation_urls"] = sorted(
                _url_key_map(prior_p.get("citation_urls")).values()
            )
            entry["note"] = (
                "Unconfirmed -- will confirm next run. A loss is only promoted to "
                "newly_lost_citations after 2 consecutive not_cited runs."
            )
        elif cur_state == "not_cited" and prior_state == "not_cited" and prior2_state == "cited":
            entry["change"] = "confirmed_citation_loss"
            entry["last_known_citation_urls"] = sorted(
                _url_key_map(prior2_p.get("citation_urls")).values()
            )
            entry["note"] = (
                "Second consecutive not_cited run after a cited run -- promoted from "
                "possible_citation_loss to a confirmed loss."
            )
        elif cur_state == prior_state:
            entry["change"] = "unchanged"
        else:
            entry["change"] = "state_changed"
            entry["note"] = (
                "Transition involving the `mixed` (intermittent-citation) state -- "
                "neither a clean gain nor a clean loss. Watch the next run."
            )

        per_provider[provider] = entry

    diff["providers"] = per_provider
    return diff


def _run_trackers(cfg: Config, skip_trackers: bool) -> dict[str, Any]:
    """Optional, account-level commercial-tracker cross-check. Called once
    per run (not per prompt) -- clearly labeled as third-party data, distinct
    from the OpenRouter model-API probing above."""
    trackers: dict[str, Any] = {}
    if skip_trackers:
        trackers["skipped"] = "Skipped via --skip-trackers."
        return trackers

    if cfg.has("PROFOUND_API_KEY"):
        try:
            trackers["profound"] = {
                "source": "third_party_commercial_tracker",
                "vendor": "Profound (tryprofound.com)",
                "data": ai_visibility.profound_visibility(cfg),
            }
        except Exception as exc:
            trackers["profound"] = {
                "source": "third_party_commercial_tracker",
                "error": http_util.sanitize_text(str(exc)),
            }
    else:
        trackers["profound"] = {
            "configured": False,
            "note": "Set PROFOUND_API_KEY to enable this supplementary cross-check "
                    "(tryprofound.com, API in beta). Not required -- the DIY probing above "
                    "is the primary, always-available mechanism.",
        }

    if cfg.has("OTTERLY_API_KEY"):
        project_id = cfg.get("OTTERLY_PROJECT_ID")
        if not project_id:
            trackers["otterly"] = {
                "source": "third_party_commercial_tracker",
                "error": "OTTERLY_API_KEY is set but OTTERLY_PROJECT_ID is not -- Otterly.AI's "
                         "visibility endpoint is scoped per project. Set OTTERLY_PROJECT_ID to "
                         "the project id shown in your Otterly.AI dashboard.",
            }
        else:
            try:
                trackers["otterly"] = {
                    "source": "third_party_commercial_tracker",
                    "vendor": "Otterly.AI (otterly.ai)",
                    "data": ai_visibility.otterly_visibility(cfg, project_id),
                }
            except Exception as exc:
                trackers["otterly"] = {
                    "source": "third_party_commercial_tracker",
                    "error": http_util.sanitize_text(str(exc)),
                }
    else:
        trackers["otterly"] = {
            "configured": False,
            "note": "Set OTTERLY_API_KEY (and OTTERLY_PROJECT_ID) to enable this supplementary "
                    "cross-check (otterly.ai, requires Standard tier or above for API access). "
                    "Not required -- the DIY probing above is the primary mechanism.",
        }

    return trackers


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Probe OpenAI/Anthropic/Perplexity/Gemini's own web-search APIs N times "
                    "per tracked prompt, majority-vote a per-provider citation state, and "
                    "diff it against history with flap-damped loss detection."
    )
    parser.add_argument(
        "--prompt", action="append", default=[],
        help="One tracked prompt (repeatable). Overrides geo_prompts/target_topics for this run.",
    )
    parser.add_argument(
        "--domain", default=None,
        help="Target domain to check citations against (default: derived from cfg.site_url).",
    )
    parser.add_argument(
        "--samples", type=int, default=DEFAULT_SAMPLES,
        help=f"Probes per prompt x provider (default {DEFAULT_SAMPLES}). A single LLM probe "
             "is a coin flip; the per-provider state is a majority vote over the non-error "
             "samples. COST: one run = configured providers x prompts x samples billed "
             "web-search LLM calls.",
    )
    parser.add_argument(
        "--skip-trackers", action="store_true",
        help="Skip the optional Profound/Otterly.AI cross-check even if configured.",
    )
    args = parser.parse_args()

    if args.samples < 1:
        parser.error("--samples must be >= 1")

    cfg = config_module.load()
    snapshots.prune(cfg)
    setup_notes: list[str] = []

    try:
        target_domain = _target_domain(cfg, args.domain)
    except MissingConfigError as exc:
        json.dump({"error": str(exc)}, sys.stdout, indent=2)
        print()
        sys.exit(1)

    prompts, prompt_source, prompt_notes = _resolve_prompts(cfg, args.prompt)
    setup_notes.extend(prompt_notes)

    if prompt_source == "none":
        result = {
            "checked": False,
            "reason": prompt_notes[-1],
            "next_step": (
                "Ask the site owner which queries matter for their AI-search visibility "
                "(the kind of question a prospective customer would type into ChatGPT/Claude/"
                "Perplexity/Gemini that this site should ideally be cited for), then either: "
                "(a) write them into .seo-engine/config.yml under `geo_prompts: [...]` for a "
                "durable, re-runnable tracked set, or (b) pass them ad hoc via repeated "
                "--prompt \"...\" flags for a one-off check."
            ),
            "target_domain": target_domain,
        }
        json.dump(result, sys.stdout, indent=2)
        print()
        sys.exit(0)

    configured_providers = [n for n in ai_visibility.probe_names(cfg) if ai_visibility._provider_configured(cfg, n)]
    if not configured_providers:
        setup_notes.append("Set OPENROUTER_API_KEY for model citation probes; see api-reference.md.")
    setup_notes.append("OpenRouter + Exa search-model samples are not consumer ChatGPT/Claude/Gemini visibility. Model/search identities start separate history series.")

    llm_calls = len(configured_providers) * len(prompts) * args.samples
    cost_note = (
        f"This run makes up to {llm_calls} billed web-search LLM API call(s): "
        f"{len(configured_providers)} configured provider(s) x {len(prompts)} prompt(s) x "
        f"{args.samples} sample(s) (--samples). Each call bills provider tokens plus "
        "web-search tool usage. Trim the tracked-prompt list or lower --samples to cut cost, "
        "but note that fewer than 2-3 samples degrades the majority vote back toward a "
        "single-probe coin flip (geo-playbook.md section 9)."
    )

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    now_iso = datetime.now(timezone.utc).isoformat()

    history = _load_history(cfg)

    records: list[dict[str, Any]] = []
    prompt_reports: list[dict[str, Any]] = []
    provider_names = ai_visibility.probe_names(cfg)

    for prompt in prompts:
        provider_samples: dict[str, list[dict[str, Any]]] = {n: [] for n in provider_names}
        for _ in range(args.samples):
            outcome = ai_visibility.probe_all(cfg, prompt, target_domain)
            for name, result in outcome["providers"].items():
                provider_samples.setdefault(name, []).append(result)

        providers_agg: dict[str, Any] = {}
        provider_detail: dict[str, Any] = {}
        for name in provider_names:
            aggregate, outcomes = _aggregate_provider_samples(
                provider_samples.get(name, []), target_domain
            )
            providers_agg[name] = aggregate
            detail = dict(aggregate)
            detail["sample_outcomes"] = outcomes
            provider_detail[name] = detail

        record = {
            "schema_version": HISTORY_SCHEMA_VERSION,
            "measurement_kind": "openrouter_search_api_sample",
            "run_id": run_id,
            "generated_at": now_iso,
            "prompt": prompt,
            "prompt_source": prompt_source,
            "target_domain": target_domain,
            "samples_per_provider": args.samples,
            "providers": providers_agg,
        }
        records.append(record)

        priors = _prior_comparable_records(history, prompt, target_domain, run_id, limit=2)
        old_format = _has_old_format_history(history, prompt, target_domain)
        diff = _diff_against_prior(record, priors, old_format)

        by_state: dict[str, list[str]] = {state: [] for state in PROVIDER_STATES}
        for name in provider_names:
            by_state[providers_agg[name]["state"]].append(name)

        prompt_reports.append({
            "prompt": prompt,
            "providers_configured": [
                n for n in provider_names if providers_agg[n]["state"] != "not_configured"
            ],
            "cited_by": by_state["cited"],
            "intermittently_cited_by": by_state["mixed"],
            "not_cited_by": by_state["not_cited"],
            "provider_errors": by_state["error"],
            "provider_detail": provider_detail,
            "diff_vs_previous_run": diff,
        })

    history_path = _append_history(cfg, records)
    setup_notes.append(
        f"Appended {len(records)} schema-v{HISTORY_SCHEMA_VERSION} record(s) "
        f"(one per tracked prompt) to {history_path.name}."
    )

    trackers = _run_trackers(cfg, args.skip_trackers)

    newly_gained: list[dict[str, Any]] = []
    possible_losses: list[dict[str, Any]] = []
    confirmed_losses: list[dict[str, Any]] = []
    url_changes: list[dict[str, Any]] = []
    indeterminate: list[dict[str, Any]] = []

    for p in prompt_reports:
        for provider, d in p["diff_vs_previous_run"].get("providers", {}).items():
            change = d.get("change")
            if change == "newly_cited":
                newly_gained.append({
                    "prompt": p["prompt"], "provider": provider, "severity": "info",
                    "urls": d.get("newly_gained_citation_urls", []),
                })
            elif change == "possible_citation_loss":
                possible_losses.append({
                    "prompt": p["prompt"], "provider": provider, "severity": "low",
                    "confidence": "unconfirmed",
                    "last_known_citation_urls": d.get("last_known_citation_urls", []),
                    "note": "Unconfirmed -- will confirm next run. Promoted to "
                            "newly_lost_citations only after 2 consecutive not_cited runs.",
                })
            elif change == "confirmed_citation_loss":
                confirmed_losses.append({
                    "prompt": p["prompt"], "provider": provider, "severity": "medium",
                    "last_known_citation_urls": d.get("last_known_citation_urls", []),
                    "note": "Confirmed by 2 consecutive not_cited runs after a cited run. "
                            "Still a stochastic measurement -- investigate, don't panic.",
                })
            elif change == "cited_but_different_pages":
                url_changes.append({
                    "prompt": p["prompt"], "provider": provider,
                    "gained_urls": d.get("newly_gained_citation_urls", []),
                    "lost_urls": d.get("newly_lost_citation_urls", []),
                })
            elif change == "indeterminate_provider_error":
                indeterminate.append({
                    "prompt": p["prompt"], "provider": provider,
                    "state_now": d.get("state_now"), "state_before": d.get("state_before"),
                    "errors": p["provider_detail"].get(provider, {}).get("errors", []),
                    "note": "Provider API error in the current or prior run -- excluded from "
                            "gained/lost counts. Re-run later; do not treat as a citation change.",
                })

    any_cited_count = sum(1 for p in prompt_reports if p["cited_by"])

    report = {
        "checked": True,
        "generated_at": now_iso,
        "run_id": run_id,
        "target_domain": target_domain,
        "prompt_source": prompt_source,
        "prompts_tracked": len(prompts),
        "samples_per_provider": args.samples,
        "diy_providers_configured": configured_providers,
        "cost_note": cost_note,
        "setup_notes": setup_notes,
        "summary": {
            "prompts_cited_by_at_least_one_provider": any_cited_count,
            "prompts_cited_by_none": len(prompt_reports) - any_cited_count,
            "newly_gained_citations_count": len(newly_gained),
            "newly_lost_citations_count": len(confirmed_losses),
            "possible_citation_losses_count": len(possible_losses),
            "citation_url_changes_count": len(url_changes),
            "indeterminate_provider_errors_count": len(indeterminate),
        },
        "newly_gained_citations": newly_gained,
        "newly_lost_citations": confirmed_losses,
        "possible_citation_losses": possible_losses,
        "citation_url_changes": url_changes,
        "indeterminate_provider_errors": indeterminate,
        "prompts": prompt_reports,
        "commercial_tracker_cross_check": trackers,
        "history_file": str(history_path),
        "history_schema_version": HISTORY_SCHEMA_VERSION,
        "methodology_note": (
            "DIY probing calls each AI vendor's own official web-search/grounding API "
            "directly (scripts.lib.ai_visibility.probe_all) and checks whether the target "
            "domain appears among the citations the API itself returned -- this is not a "
            "scrape of any chat UI, which likely violates ToS (see references/geo-playbook.md "
            "section 9). Because a single LLM probe is stochastic, each prompt x provider is "
            f"probed {args.samples} time(s) and folded into a state: cited (majority of "
            "non-error samples), not_cited (zero cited samples), mixed (some but short of a "
            "majority), error (every sample errored -- an unknown, never counted as not "
            "cited), not_configured. citation_urls is the union across samples of "
            "target-domain-matching citations (Gemini citations are identified by title, "
            "since its grounding URIs are opaque redirects). The Gemini result reflects the "
            "Gemini API's own Search-grounding feature, a useful proxy but not literally the "
            "same system as Google AI Overviews/AI Mode in Search itself (those have no "
            "public API -- see api-reference.md). commercial_tracker_cross_check data "
            "(Profound/Otterly.AI, if configured) is third-party dashboard data, kept in its "
            "own labeled block -- never merge it into the per-prompt provider results above, "
            "since it measures visibility over that vendor's own prompt set/category "
            "taxonomy, not necessarily the same prompts tracked here."
        ),
        "interpretation_guidance": (
            "A prompt with zero configured providers tells you nothing (see "
            "diy_providers_configured) -- configure at least one API key before drawing any "
            "conclusion from that prompt's result. 'not_cited_by' is not itself an actionable "
            "defect to 'fix' -- per references/geo-playbook.md section 2, AI platforms are "
            "not a monolith, and most citation-worthiness is a function of content substance "
            "and off-site authority signals (sections 5-6), not something this monitoring "
            "skill can auto-remediate. Signal priority: newly_lost_citations (confirmed by "
            "two consecutive runs) is the time-sensitive signal worth investigating first; "
            "possible_citation_losses is a watchlist, not an alarm -- it will confirm or "
            "clear on the next run; indeterminate_provider_errors are measurement failures "
            "(rate limits, outages), not visibility changes -- re-run later; "
            "newly_gained_citations shows which of the site's own pages are actually earning "
            "citations, useful input for geo-optimize/seo-content-optimize about what's "
            "already working. A 'mixed' state means intermittent citation across samples -- "
            "expected for borderline prompts, not a defect."
        ),
    }

    reports_dir = cfg.reports_dir
    ts = time.strftime("%Y%m%d-%H%M%S")
    report_path = reports_dir / f"ai-visibility-{ts}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_file"] = str(report_path)

    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
