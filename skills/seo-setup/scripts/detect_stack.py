"""Detect the host repo's tech stack: framework, static-source vs. build-output
directories, and whether a sitemap already exists.

Scans the CURRENT WORKING DIRECTORY the script is invoked from (the target
repo root), NOT the seo-engine installation directory. Run this from the root
of the website repo:

    cd /path/to/target-repo
    python3 <seo-engine>/skills/seo-setup/scripts/detect_stack.py

This script only reads the filesystem — it makes no network calls and needs
no API keys, so it always produces a full result. It is report-only: it never
writes anything; the seo-setup agent writes .seo-engine/config.yml per
SKILL.md, copying the `suggested_config` block from this script's output.

The two directory fields matter because they are opposites:
  * `static_source_dir` — deploys VERBATIM to the site root. The only safe
    place to write files that must ship (IndexNow key file, llms.txt,
    robots.txt).
  * `build_output_dir` — wiped/regenerated on every build. NEVER write files
    here; anything placed there silently vanishes on the next build. The
    classic trap is Hugo, where /public is the BUILD OUTPUT (source assets
    live in /static) — Gatsby has the same public-is-output layout.

Output: a single JSON object to stdout. See `detect()` for the exact shape.
"""

import json
import re
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


# Framework signal definitions, ordered by specificity — the first match wins
# where signals could overlap (e.g. Next.js also ships a package.json dep on
# "react", but "next" is checked first).
#
# static_source_dir: deployed verbatim (safe to write files that must ship).
# build_output_dir: wiped/regenerated every build (NEVER write files there).
FRAMEWORK_SIGNALS = [
    {
        "framework": "next.js",
        "config_globs": ["next.config.js", "next.config.mjs", "next.config.ts"],
        "package_deps": ["next"],
        "static_source_dir": "public",
        "build_output_dir": ".next",
        "notes": "Static assets in /public deploy verbatim; the build output is /.next "
                 "(or /out when `output: 'export'` is configured) and is wiped every "
                 "build. Pages/app router source is server-rendered or SSG at build "
                 "time — fix metadata/schema at the source (page/layout) level.",
    },
    {
        "framework": "astro",
        "config_globs": ["astro.config.js", "astro.config.mjs", "astro.config.ts"],
        "package_deps": ["astro"],
        "static_source_dir": "public",
        "build_output_dir": "dist",
        "notes": "Static source assets live in /public and pass through unchanged; "
                 "build output goes to /dist by default (configurable via outDir) and "
                 "is regenerated every build.",
    },
    {
        "framework": "nuxt",
        "config_globs": ["nuxt.config.js", "nuxt.config.mjs", "nuxt.config.ts"],
        "package_deps": ["nuxt"],
        "static_source_dir": "public",
        "build_output_dir": ".output",
        "notes": "Static source assets in /public pass through unchanged; the Nitro "
                 "build output goes to /.output (served from /.output/public) and is "
                 "wiped every build.",
    },
    {
        "framework": "sveltekit",
        "config_globs": ["svelte.config.js", "svelte.config.mjs", "svelte.config.cjs"],
        "package_deps": ["@sveltejs/kit"],
        # svelte.config.* alone is NOT SvelteKit — plain Svelte + Vite ships the
        # same config filename. The @sveltejs/kit dependency is required.
        "require_dep": True,
        "static_source_dir": "static",
        "build_output_dir": "build",
        "notes": "Static source assets in /static deploy verbatim; adapter-dependent "
                 "build output (often /build) is regenerated every build.",
    },
    {
        "framework": "gatsby",
        "config_globs": ["gatsby-config.js", "gatsby-config.ts"],
        "package_deps": ["gatsby"],
        "static_source_dir": "static",
        "build_output_dir": "public",
        "notes": "Static source assets in /static deploy verbatim; /public is Gatsby's "
                 "BUILD OUTPUT and is wiped every build — never write files there "
                 "(easy to invert because other stacks use /public as source).",
    },
    {
        "framework": "hugo",
        "config_globs": ["hugo.toml", "hugo.yaml", "hugo.yml",
                         "config.toml", "config.yaml", "config.yml"],
        "package_deps": [],
        # config.toml/config.yml are generic filenames shared by many tools —
        # only claim Hugo when the Hugo project structure is present too.
        "generic_configs_require_dirs": {
            "configs": {"config.toml", "config.yaml", "config.yml"},
            "dirs": ["content", "layouts"],
        },
        "static_source_dir": "static",
        "build_output_dir": "public",
        "notes": "Static-site generator, no package.json required. /static deploys "
                 "verbatim; /public is Hugo's BUILD OUTPUT, wiped on every `hugo` "
                 "build — the classic place people wrongly drop files that must ship.",
    },
    {
        "framework": "jekyll",
        "config_globs": ["_config.yml"],
        "package_deps": [],
        "static_source_dir": ".",
        "build_output_dir": "_site",
        "notes": "Static-site generator (Ruby/Bundler, not Node). The project root "
                 "deploys verbatim (files/dirs not starting with _ are copied through), "
                 "so the repo root is the static source; /_site is the build output "
                 "and is regenerated every build.",
    },
    {
        "framework": "eleventy",
        "config_globs": [".eleventy.js", "eleventy.config.js",
                         "eleventy.config.mjs", "eleventy.config.cjs"],
        "package_deps": ["@11ty/eleventy"],
        "static_source_dir": ".",
        "build_output_dir": "_site",
        "notes": "Input defaults to the project root (passthrough-copied files ship "
                 "verbatim); build output goes to /_site by default and is regenerated "
                 "every build. Check the eleventy config for custom input/output dirs.",
    },
    {
        "framework": "vite",
        "config_globs": ["vite.config.js", "vite.config.mjs", "vite.config.ts"],
        "package_deps": ["vite"],
        "static_source_dir": "public",
        "build_output_dir": "dist",
        "notes": "Generic Vite build (React/Vue/Svelte/vanilla) — static source assets "
                 "in /public pass through unchanged; build output goes to /dist by "
                 "default and is wiped every build.",
    },
]

# Fallback package.json dependency checks when no config file matched, ordered
# by specificity (framework metapackages checked before bare-library deps).
PACKAGE_DEP_FALLBACKS = [
    ("react", {
        "static_source_dir": "public",
        "build_output_dir": "build",
        "note": "react (no framework config detected — likely CRA, a custom webpack/vite "
                "setup, or an unconfigured React app). CRA convention: /public is source, "
                "/build is output — verify before writing files.",
    }),
    ("vue", {
        "static_source_dir": "public",
        "build_output_dir": "dist",
        "note": "vue (no framework config detected — likely a custom build setup). "
                "vue-cli convention: /public is source, /dist is output — verify before "
                "writing files.",
    }),
]

_NEXT_EXPORT_RE = re.compile(r"output\s*:\s*['\"]export['\"]")


def _read_package_json(repo_root: Path) -> dict:
    pkg_path = repo_root / "package.json"
    if not pkg_path.is_file():
        return {}
    try:
        return json.loads(pkg_path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return {}


def _all_declared_deps(pkg: dict) -> set:
    deps = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        deps.update((pkg.get(key) or {}).keys())
    return deps


def _dir_info(repo_root: Path, rel_path) -> dict:
    """{"path": <repo-relative dir or None>, "exists": <checked on disk>}."""
    if rel_path is None:
        return {"path": None, "exists": False}
    return {"path": rel_path, "exists": (repo_root / rel_path).is_dir()}


def _next_export_mode(repo_root: Path) -> bool:
    """True when next.config.* configures `output: 'export'` (static export —
    the build output then lands in /out instead of /.next)."""
    for name in ("next.config.js", "next.config.mjs", "next.config.ts"):
        candidate = repo_root / name
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _NEXT_EXPORT_RE.search(text):
            return True
    return False


def _signal_matches(signal: dict, repo_root: Path,
                    matched_config, matched_dep) -> "tuple[bool, list]":
    """Apply per-framework tightening rules. Returns (matches, extra_evidence)."""
    if not (matched_config or matched_dep):
        return False, []
    if signal.get("require_dep") and not matched_dep:
        # e.g. svelte.config.js without @sveltejs/kit = plain Svelte/Vite,
        # not SvelteKit — fall through so the vite signal can claim it.
        return False, []
    gate = signal.get("generic_configs_require_dirs")
    if gate and matched_config in gate["configs"] and not matched_dep:
        present = [d for d in gate["dirs"] if (repo_root / d).is_dir()]
        if not present:
            return False, []
        return True, [f"project dir(s) present: {', '.join('/' + d for d in present)} "
                      f"(required to disambiguate the generic {matched_config})"]
    return True, []


def detect_framework(repo_root: Path) -> dict:
    pkg = _read_package_json(repo_root)
    declared_deps = _all_declared_deps(pkg)

    for signal in FRAMEWORK_SIGNALS:
        matched_config = next(
            (name for name in signal["config_globs"] if (repo_root / name).is_file()),
            None,
        )
        matched_dep = next((d for d in signal["package_deps"] if d in declared_deps), None)
        matches, extra_evidence = _signal_matches(signal, repo_root, matched_config, matched_dep)
        if not matches:
            continue

        evidence = []
        if matched_config:
            evidence.append(f"config file: {matched_config}")
        if matched_dep:
            evidence.append(f"package.json dependency: {matched_dep}")
        evidence.extend(extra_evidence)

        static_source = signal["static_source_dir"]
        build_output = signal["build_output_dir"]
        notes = signal["notes"]
        if signal["framework"] == "next.js" and _next_export_mode(repo_root):
            build_output = "out"
            evidence.append("next.config.* sets output: 'export' — static export mode, "
                            "build output is /out")

        return {
            "framework": signal["framework"],
            "confidence": "high" if (matched_config and matched_dep) else "medium",
            "evidence": evidence,
            "static_source_dir": _dir_info(repo_root, static_source),
            "build_output_dir": _dir_info(repo_root, build_output),
            "notes": notes,
        }

    for dep_name, fallback in PACKAGE_DEP_FALLBACKS:
        if dep_name in declared_deps:
            return {
                "framework": dep_name,
                "confidence": "low",
                "evidence": [f"package.json dependency: {dep_name}"],
                "static_source_dir": _dir_info(repo_root, fallback["static_source_dir"]),
                "build_output_dir": _dir_info(repo_root, fallback["build_output_dir"]),
                "notes": fallback["note"],
            }

    # Bare static site: an index.html with no JS framework signal at all.
    if (repo_root / "index.html").is_file() and not pkg:
        return {
            "framework": "static-html",
            "confidence": "medium",
            "evidence": ["index.html present, no package.json"],
            "static_source_dir": _dir_info(repo_root, "."),
            "build_output_dir": _dir_info(repo_root, None),
            "notes": "No build step detected — treat the repo root (or wherever index.html "
                     "lives) as the served site root; fix pages directly in place. There "
                     "is no build output dir to avoid.",
        }
    if (repo_root / "index.html").is_file():
        return {
            "framework": "static-html",
            "confidence": "low",
            "evidence": ["index.html present alongside a package.json with no matched "
                         "framework — could be a bundler output or a hand-rolled site"],
            "static_source_dir": _dir_info(repo_root, "."),
            "build_output_dir": _dir_info(repo_root, None),
            "notes": "Verify manually: check package.json scripts for a build step before "
                     "assuming this is hand-written static HTML.",
        }

    return {
        "framework": "unknown",
        "confidence": "none",
        "evidence": [],
        "static_source_dir": _dir_info(repo_root, None),
        "build_output_dir": _dir_info(repo_root, None),
        "notes": "No recognized framework config, package.json dependency, or bare "
                 "index.html found. Ask the user directly what serves this site, or "
                 "look for a Dockerfile / deploy config (e.g. vercel.json, netlify.toml, "
                 "wrangler.toml) for further clues.",
    }


SITEMAP_CANDIDATE_PATHS = [
    "sitemap.xml",
    "public/sitemap.xml",
    "static/sitemap.xml",
    "dist/sitemap.xml",
    "build/sitemap.xml",
    "_site/sitemap.xml",
    ".output/public/sitemap.xml",
    "app/sitemap.xml",
    "src/sitemap.xml",
]

# Frameworks that generate sitemap.xml dynamically via a route/plugin rather
# than a static file checked into the repo — grep for the generator pattern
# instead of a literal file.
DYNAMIC_SITEMAP_SIGNALS = {
    "next.js": [("app/sitemap.ts", "Next.js App Router sitemap route (MetadataRoute.Sitemap)"),
                ("app/sitemap.js", "Next.js App Router sitemap route (MetadataRoute.Sitemap)"),
                ("pages/sitemap.xml.js", "Next.js Pages Router API-route sitemap"),
                ("pages/sitemap.xml.ts", "Next.js Pages Router API-route sitemap"),
                ("next-sitemap.config.js", "next-sitemap package config"),
                ("next-sitemap.config.mjs", "next-sitemap package config"),
                ("next-sitemap.config.ts", "next-sitemap package config")],
    "astro": [("astro.config.mjs", "check for @astrojs/sitemap integration"),
              ("astro.config.js", "check for @astrojs/sitemap integration"),
              ("astro.config.ts", "check for @astrojs/sitemap integration")],
    "nuxt": [("nuxt.config.ts", "check for @nuxtjs/sitemap module"),
             ("nuxt.config.js", "check for @nuxtjs/sitemap module")],
    "gatsby": [("gatsby-config.js", "check for gatsby-plugin-sitemap"),
               ("gatsby-config.ts", "check for gatsby-plugin-sitemap")],
}


def detect_sitemap(repo_root: Path, framework: str) -> dict:
    for rel_path in SITEMAP_CANDIDATE_PATHS:
        candidate = repo_root / rel_path
        if candidate.is_file():
            return {
                "found": True,
                "kind": "static_file",
                "path": str(candidate.relative_to(repo_root)),
                "notes": "Static sitemap.xml file present at this path.",
            }

    dynamic_signals = DYNAMIC_SITEMAP_SIGNALS.get(framework, [])
    for rel_path, note in dynamic_signals:
        candidate = repo_root / rel_path
        if candidate.is_file():
            try:
                text = candidate.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                text = ""
            if "sitemap" in text.lower() or rel_path.endswith(("sitemap.ts", "sitemap.js")):
                return {
                    "found": True,
                    "kind": "dynamic_route_or_plugin",
                    "path": rel_path,
                    "notes": note + " — verify this is actually wired up and reachable at "
                                     "/sitemap.xml once built/deployed; a config reference "
                                     "alone doesn't guarantee the route is registered.",
                }

    return {
        "found": False,
        "kind": None,
        "path": None,
        "notes": "No sitemap.xml (static or dynamic-route) detected. See "
                 "references/seo-playbook.md §2 — a valid, complete sitemap kept in "
                 "sync with what's indexable is part of the non-negotiable technical "
                 "foundation. Flag for the seo-technical-audit / seo-indexing skills.",
    }


def detect_existing_seo_engine_config(repo_root: Path) -> dict:
    config_path = repo_root / ".seo-engine" / "config.yml"
    if not config_path.is_file():
        return {"found": False, "path": None, "notes": "No prior .seo-engine/config.yml — safe to write a new one."}
    return {
        "found": True,
        "path": str(config_path.relative_to(repo_root)),
        "notes": "A .seo-engine/config.yml already exists. DO NOT overwrite it without "
                 "showing the human/agent a diff first — re-running seo-setup should "
                 "confirm and merge, not clobber prior setup (e.g. previously filled-in "
                 "target topics/locales).",
    }


def build_suggested_config(framework_info: dict) -> dict:
    """Ready-to-copy keys for .seo-engine/config.yml (the seo-setup agent
    merges these in after confirming site_url with the user — site_url is
    deliberately absent because this script cannot know it)."""
    suggested = {}
    if framework_info["framework"] != "unknown":
        suggested["framework"] = framework_info["framework"]
    for key in ("static_source_dir", "build_output_dir"):
        path = framework_info[key]["path"]
        if path is not None:
            suggested[key] = path
    return suggested


def detect(repo_root: Path) -> dict:
    framework_info = detect_framework(repo_root)
    sitemap_info = detect_sitemap(repo_root, framework_info["framework"])
    existing_config = detect_existing_seo_engine_config(repo_root)

    return {
        "scanned_dir": str(repo_root),
        "framework": framework_info,
        "dir_semantics": {
            "static_source_dir": "deploys VERBATIM to the site root — the only safe place "
                                 "for files that must ship (IndexNow key file, llms.txt, "
                                 "robots.txt)",
            "build_output_dir": "wiped/regenerated on every build — NEVER write files here",
        },
        "sitemap": sitemap_info,
        "existing_seo_engine_config": existing_config,
        "suggested_config": build_suggested_config(framework_info),
        "next_step": (
            "Do NOT auto-write .seo-engine/config.yml from this report alone. The agent "
            "must confirm the production site_url with the user first (this script cannot "
            "know it reliably — a repo's local dev/staging URL, a custom domain, and the "
            "framework's default deploy URL are all plausible and only the user can confirm "
            "which is canonical), then write .seo-engine/config.yml per the shape documented "
            "in SKILL.md, merging in the `suggested_config` block above (framework, "
            "static_source_dir, build_output_dir). If existing_seo_engine_config.found is "
            "true, confirm before overwriting."
        ),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Detect the host repo's framework, static-source/build-output dirs, "
                    "and sitemap presence."
    )
    parser.add_argument(
        "--dir", default=None,
        help="Directory to scan (default: current working directory, i.e. the host repo root).",
    )
    args = parser.parse_args()

    # Intentionally independent of scripts.lib.config's repo-root resolution:
    # this script scans literally the directory it's invoked from (or --dir),
    # per the seo-setup contract of operating on "the host repo root, not the
    # seo-engine folder itself."
    scan_dir = Path(args.dir).resolve() if args.dir else Path.cwd().resolve()

    if not scan_dir.is_dir():
        json.dump({"error": f"Not a directory: {scan_dir}"}, sys.stdout, indent=2)
        print()
        sys.exit(1)

    result = detect(scan_dir)
    json.dump(result, sys.stdout, indent=2)
    print()
