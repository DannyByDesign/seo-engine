"""Configuration resolution for seo-engine scripts.

Resolution order (later wins for the same key):
  1. .env at the target repo root (never committed; see .env.example)
  2. Process environment (always wins — lets cron/CI override files)

Never inherit another workspace's engine-adjacent credentials.

Site-level settings (domain, sitemap, target topics, ...) live in
`.seo-engine/config.yml` at the target repo root — created by the `seo-setup`
skill and private by default alongside the workspace's operating decisions.

The target repo root is discovered by walking up from the current working
directory (`.git` / `.seo-engine` / `package.json` markers). Set the
`SEO_REPO_ROOT` env var to pin it explicitly (recommended for cron/CI).

Every accessor raises `MissingConfigError` with the exact env var name and a
one-line remediation so agents can self-serve the fix.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

try:
    import yaml
except ImportError:
    yaml = None

INTEGRATION_ENV_VARS: dict[str, dict[str, list[str]]] = {
    "google_search_console": {"any": ["GOOGLE_APPLICATION_CREDENTIALS", "GSC_SERVICE_ACCOUNT_JSON"]},
    "google_analytics": {"any": ["GOOGLE_APPLICATION_CREDENTIALS", "GSC_SERVICE_ACCOUNT_JSON"], "all": ["GA4_PROPERTY_ID"]},
    "posthog": {"all": ["POSTHOG_PERSONAL_API_KEY", "POSTHOG_PROJECT_ID", "POSTHOG_HOST"]},
    "pagespeed_insights": {"all": ["GOOGLE_PSI_API_KEY"]},
    "ahrefs": {"all": ["AHREFS_API_KEY"]},
    "dataforseo": {"all": ["DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD"]},
    "firecrawl": {"all": ["FIRECRAWL_API_KEY"]},
    "brave_search": {"all": ["BRAVE_SEARCH_API_KEY"]},
    "languagetool": {"all": ["LANGUAGETOOL_URL"]},
    "indexnow": {"all": ["INDEXNOW_API_KEY"]},
    "semrush": {"all": ["SEMRUSH_API_KEY"]},
    "bing_webmaster": {"all": ["BING_WEBMASTER_API_KEY"]},
    "openai": {"all": ["OPENAI_API_KEY"]},
    "anthropic": {"all": ["ANTHROPIC_API_KEY"]},
    "perplexity": {"all": ["PERPLEXITY_API_KEY"]},
    "gemini": {"all": ["GOOGLE_GEMINI_API_KEY"]},
    "profound": {"all": ["PROFOUND_API_KEY"]},
    "otterly": {"all": ["OTTERLY_API_KEY"]},
    "sociavault": {"all": ["SOCIAVAULT_API_KEY"]},
    "github": {"all": ["GITHUB_TOKEN"]},
    "notion": {"all": ["NOTION_TOKEN"]},
}

_PLACEHOLDER_MARKERS = ("your-", "<", "/path/to/", "changeme", "example.com")


class MissingConfigError(RuntimeError):
    """Raised when a required env var or config value is absent."""

    def __init__(self, key: str, hint: str):
        self.key = key
        self.hint = hint
        super().__init__(
            f"Missing configuration: {key}. {hint} "
            f"(set it in .env at the repo root — see .env.example in seo-engine)"
        )


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def find_repo_root(start: Optional[Path] = None) -> Path:
    """The target repo root: `SEO_REPO_ROOT` env var if set, else walk upward
    from `start` (default: cwd) to the nearest directory that looks like a
    project root (.git, .seo-engine, or package.json)."""
    pinned = os.environ.get("SEO_REPO_ROOT", "").strip()
    if pinned:
        pinned_path = Path(pinned).resolve()
        if not pinned_path.is_dir():
            raise MissingConfigError(
                "SEO_REPO_ROOT",
                f"SEO_REPO_ROOT is set to {pinned!r} but that directory does not exist.",
            )
        return pinned_path
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        for marker in (".git", ".seo-engine", "package.json"):
            if (candidate / marker).exists():
                return candidate
    return cur


def _parse_env_file(path: Path) -> dict[str, str]:
    """Minimal .env parser: KEY=VALUE lines, `#` comments, optional quotes,
    optional `export ` prefix. No interpolation."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _engine_root() -> Path:
    """Directory containing the seo-engine installation (two levels above lib/)."""
    return Path(__file__).resolve().parent.parent.parent


@dataclass
class Config:
    repo_root: Path
    env: dict[str, str] = field(default_factory=dict)
    site: dict[str, Any] = field(default_factory=dict)


    @classmethod
    def load(cls, start: Optional[Path] = None) -> "Config":
        root = find_repo_root(start)
        env: dict[str, str] = {}
        env.update(_parse_env_file(root / ".env"))
        env.update(os.environ)

        site: dict[str, Any] = {}
        site_cfg = root / ".seo-engine" / "config.yml"
        if site_cfg.is_file():
            if yaml is None:
                raise RuntimeError(
                    "PyYAML is required to read .seo-engine/config.yml — "
                    "run: python3 -m pip install -r <seo-engine>/requirements.txt"
                )
            site = yaml.safe_load(site_cfg.read_text(encoding="utf-8")) or {}
        return cls(repo_root=root, env=env, site=site)


    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self.env.get(key, default)

    def require(self, key: str, hint: str) -> str:
        value = self.env.get(key, "").strip()
        if not value or _is_placeholder(value):
            raise MissingConfigError(key, hint)
        return value

    def has(self, key: str) -> bool:
        value = self.env.get(key, "").strip()
        return bool(value) and not _is_placeholder(value)


    @property
    def site_url(self) -> str:
        url = str(self.site.get("site_url") or self.env.get("SEO_SITE_URL", "")).strip()
        if not url or _is_placeholder(url):
            raise MissingConfigError(
                "SEO_SITE_URL",
                "Set site_url in .seo-engine/config.yml (run the seo-setup skill) "
                "or export SEO_SITE_URL.",
            )
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise MissingConfigError(
                "SEO_SITE_URL",
                f"site_url must be a full http(s) URL (got {url!r}).",
            )
        return url.rstrip("/")

    @property
    def state_dir(self) -> Path:
        d = self.repo_root / ".seo-engine" / "state"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def reports_dir(self) -> Path:
        d = self.repo_root / ".seo-engine" / "reports"
        d.mkdir(parents=True, exist_ok=True)
        return d


    def integration_available(self, name: str) -> bool:
        spec = INTEGRATION_ENV_VARS[name]
        return (not spec.get("any") or any(self.has(var) for var in spec["any"])) and all(self.has(var) for var in spec.get("all", []))

    def available_integrations(self) -> dict[str, bool]:
        """Which optional integrations are configured. Skills use this to
        decide what they can do and to tell the user what would unlock more."""
        return {name: self.integration_available(name) for name in INTEGRATION_ENV_VARS}


def save_site_config(cfg: Config, updates: dict[str, Any]) -> Path:
    """Merge `updates` into .seo-engine/config.yml (creating it if needed) and
    refresh cfg.site in place. Round-trips values only — comments are not
    preserved, so seo-setup writes this file comment-free by convention."""
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required to write .seo-engine/config.yml — "
            "run: python3 -m pip install -r <seo-engine>/requirements.txt"
        )
    path = cfg.repo_root / ".seo-engine" / "config.yml"
    current: dict[str, Any] = {}
    if path.is_file():
        current = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    current.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".yml.tmp")
    tmp.write_text(yaml.safe_dump(current, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    cfg.site = current
    return path


def load(start: Optional[Path] = None) -> Config:
    """Module-level convenience: `from scripts.lib import config; cfg = config.load()`."""
    return Config.load(start)
