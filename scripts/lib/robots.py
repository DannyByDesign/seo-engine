"""RFC 9309-correct robots.txt parsing, evaluation, and fetching.

One implementation shared by the crawler (politeness) and geo-optimize's
AI-crawler audit (policy analysis). The two subtleties most hand-rolled
parsers get wrong — and that this module exists to get right:

* **All matching groups merge.** RFC 9309 §2.2.1: if more than one group
  matches a user agent, their rules MUST be combined. Keeping only the last
  matching group produces false "not blocked" verdicts.
* **An empty pattern matches nothing.** `Allow:` with no value is a no-op,
  not a blanket allow that nullifies `Disallow: /`.

Evaluation is longest-match-wins (pattern octet length), Allow wins ties.
Patterns support `*` (any chars) and a trailing `$` (end anchor).

Fetch semantics (RFC 9309 §2.3.1):
* 2xx  -> parse the body
* 4xx (incl. 401/403/404) -> **allow all** (no robots restrictions exist)
* 5xx / network failure   -> **disallow all** (conservative: the site may
  have restrictions we could not read), surfaced with an explicit status so
  callers can say *why* a crawl produced nothing instead of failing silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

from . import http_util


@dataclass
class Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[str, str]] = field(default_factory=list)
    crawl_delay: Optional[float] = None


@dataclass
class RobotsPolicy:
    source_status: int = 200
    allow_all: bool = False
    disallow_all: bool = False
    groups: list[Group] = field(default_factory=list)
    sitemaps: list[str] = field(default_factory=list)
    fetch_error: str = ""


    def _matching_groups(self, user_agent: str) -> list[Group]:
        token = _product_token(user_agent)
        exact = [g for g in self.groups if token in g.agents]
        if exact:
            return exact
        return [g for g in self.groups if "*" in g.agents]

    def rules_for(self, user_agent: str) -> list[tuple[str, str]]:
        """RFC 9309 merge: the combined rules of ALL matching groups."""
        merged: list[tuple[str, str]] = []
        for group in self._matching_groups(user_agent):
            merged.extend(group.rules)
        return merged

    def allowed(self, user_agent: str, url: str) -> bool:
        if self.allow_all:
            return True
        if self.disallow_all:
            return False
        return _evaluate(self.rules_for(user_agent), _url_path(url)) != "disallow"

    def crawl_delay(self, user_agent: str) -> Optional[float]:
        delays = [g.crawl_delay for g in self._matching_groups(user_agent)
                  if g.crawl_delay is not None]
        return max(delays) if delays else None

    def disallowed_paths(self, user_agent: str) -> list[str]:
        """Non-empty Disallow patterns applying to this agent (for surfacing
        partial blocks — a bot allowed at / but blocked from /blog/)."""
        return [p for kind, p in self.rules_for(user_agent)
                if kind == "disallow" and p]


def _product_token(user_agent: str) -> str:
    """Robots groups name product tokens (e.g. `GPTBot`), not full UA
    strings; fold case and take the bare token."""
    return user_agent.strip().lower()


def _url_path(url: str) -> str:
    try:
        parsed = urlparse(url)
    except ValueError:
        return "/"
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return path


def _pattern_to_re(pattern: str) -> re.Pattern:
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    regex = ".*".join(re.escape(part) for part in pattern.split("*"))
    return re.compile("^" + regex + ("$" if anchored else ""))


def _evaluate(rules: list[tuple[str, str]], path: str) -> str:
    """'allow' | 'disallow' | 'none'. Longest pattern wins; Allow wins ties.
    Empty patterns match nothing (RFC 9309 §2.2.2)."""
    best_kind = "none"
    best_len = -1
    for kind, pattern in rules:
        if not pattern:
            continue
        if _pattern_to_re(pattern).match(path):
            length = len(pattern)
            if length > best_len or (length == best_len and kind == "allow"):
                best_len = length
                best_kind = kind
    return best_kind


def parse(body: str, source_status: int = 200) -> RobotsPolicy:
    """Parse robots.txt. Blank lines do NOT terminate groups; consecutive
    User-agent lines merge into one group; a User-agent line after rules
    starts a new group."""
    policy = RobotsPolicy(source_status=source_status)
    current: Optional[Group] = None
    seen_rules_in_current = False

    for raw in (body or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()

        if key == "user-agent":
            if current is None or seen_rules_in_current:
                current = Group()
                policy.groups.append(current)
                seen_rules_in_current = False
            current.agents.append(value.lower())
        elif key in ("allow", "disallow"):
            if current is None:
                continue
            current.rules.append((key, value))
            seen_rules_in_current = True
        elif key == "crawl-delay":
            if current is not None:
                try:
                    current.crawl_delay = float(value)
                except ValueError:
                    pass
                seen_rules_in_current = True
        elif key == "sitemap":
            if value:
                policy.sitemaps.append(value)

    return policy


def fetch(site_url: str, user_agent: str = http_util.USER_AGENT) -> RobotsPolicy:
    """Fetch and parse a site's robots.txt with the engine's own UA (the
    stdlib robotparser fetches as `Python-urllib`, which WAFs routinely 403 —
    and then treats that 403 as disallow-all, silently emptying crawls)."""
    robots_url = urljoin(site_url, "/robots.txt")
    try:
        resp = http_util.get(robots_url, headers={"User-Agent": user_agent})
    except http_util.HttpError as exc:
        policy = RobotsPolicy(source_status=-1, disallow_all=True)
        policy.fetch_error = str(exc)
        return policy

    if resp.status_code >= 500:
        policy = RobotsPolicy(source_status=resp.status_code, disallow_all=True)
        policy.fetch_error = f"robots.txt returned HTTP {resp.status_code}"
        return policy
    if resp.status_code >= 400:
        return RobotsPolicy(source_status=resp.status_code, allow_all=True)
    return parse(resp.text or "", source_status=resp.status_code)
