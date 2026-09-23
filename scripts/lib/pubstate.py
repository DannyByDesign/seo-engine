"""Shared state helpers for the pub-* skills: the YAML files that live inside
a publication directory (strategy.yml, topic-map.yml, seers.yml) and the
per-publication JSON state under .seo-engine/state/.

Kept deliberately small — load/save with defaults, id minting, and the one
text-overlap measure every curate/enhance script uses so that "similar
topic" means the same thing everywhere (cannibalization checks, spoke
dedupe, internal-link candidates).
"""

from __future__ import annotations

import json
import os
import tempfile
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import yaml
except ImportError:
    yaml = None

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "how", "in", "into", "is", "it",
    "its", "of", "on", "or", "our", "than", "that", "the", "their", "this", "to", "up", "vs", "was", "were", "will",
    "with", "your", "you", "we", "i", "us", "about", "all", "also", "can", "more", "not", "one", "out", "so", "if",
    "no", "do", "does", "get", "new", "use", "used", "using", "what", "why", "when", "which", "who", "should",
}
_WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _need_yaml() -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required — python3 -m pip install -r requirements.txt")


def load_yaml(path: Path, default: Any = None) -> Any:
    _need_yaml()
    if not Path(path).is_file():
        return default if default is not None else {}
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or (default if default is not None else {})


def atomic_text(path: Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text); stream.flush(); os.fsync(stream.fileno())
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return path


def save_yaml(path: Path, data: Any) -> Path:
    _need_yaml()
    return atomic_text(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def load_json(path: Path, default: Any = None) -> Any:
    if not Path(path).is_file():
        return default if default is not None else {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default if default is not None else {}


def save_json(path: Path, data: Any) -> Path:
    return atomic_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def strategy_path(root: Path) -> Path:
    return Path(root) / "strategy.yml"


def topic_map_path(root: Path) -> Path:
    return Path(root) / "topic-map.yml"


def seers_path(root: Path) -> Path:
    return Path(root) / "seers.yml"


def competitors_dir(root: Path) -> Path:
    return Path(root) / "competitors"


DEFAULT_STRATEGY: dict[str, Any] = {
    "client": {"name": "", "domain": "", "description": "", "slogan": ""},
    "direction": "",
    "priority_topics": [],
    "stances": [],
    "avoid_topics": [],
    "ranking_targets": [],
    "landings": [],
    "competitors": [],
    "brand_voice": {"writing_style": "", "tone": "", "kernel": "editorial"},
    "mention": {"degree": "subtle", "rate": 0.1},
}


def load_strategy(root: Path) -> dict[str, Any]:
    data = load_yaml(strategy_path(root), {})
    merged = json.loads(json.dumps(DEFAULT_STRATEGY))
    for key, value in (data or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def save_strategy(root: Path, strategy: dict[str, Any]) -> Path:
    strategy["updated_at"] = now_iso()
    return save_yaml(strategy_path(root), strategy)


def load_topic_map(root: Path) -> dict[str, Any]:
    data = load_yaml(topic_map_path(root), {})
    data.setdefault("pillars", [])
    return data


def save_topic_map(root: Path, topic_map: dict[str, Any]) -> Path:
    topic_map["updated_at"] = now_iso()
    return save_yaml(topic_map_path(root), topic_map)


def all_spokes(topic_map: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [(pillar, spoke) for pillar in topic_map.get("pillars", []) for spoke in pillar.get("spokes", [])]


def next_spoke_id(topic_map: dict[str, Any]) -> str:
    used = {s.get("id", "") for _, s in all_spokes(topic_map)}
    n = len(used) + 1
    while f"sp-{n:04d}" in used:
        n += 1
    return f"sp-{n:04d}"


def find_spoke(topic_map: dict[str, Any], spoke_id: str) -> Optional[dict[str, Any]]:
    for _, spoke in all_spokes(topic_map):
        if spoke.get("id") == spoke_id:
            return spoke
    return None


def state_path(cfg: Any, name: str, slug: str) -> Path:
    return Path(cfg.state_dir) / f"pub-{name}-{slug}.json"


def report_path(cfg: Any, name: str, slug: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(cfg.reports_dir) / f"pub-{name}-{slug}-{stamp}.json"


def tokens(text: str) -> Counter:
    return Counter(w for w in _WORD_RE.findall((text or "").lower()) if w not in STOPWORDS and len(w) > 2)


def overlap(a: str, b: str) -> float:
    """Cosine similarity over stop-word-filtered term counts (0..1)."""
    ta, tb = tokens(a), tokens(b)
    shared = set(ta) & set(tb)
    if not shared:
        return 0.0
    num = sum(ta[t] * tb[t] for t in shared)
    den = (sum(v * v for v in ta.values()) ** 0.5) * (sum(v * v for v in tb.values()) ** 0.5)
    return num / den if den else 0.0


def best_overlap(text: str, candidates: list[str]) -> tuple[float, Optional[str]]:
    best, best_text = 0.0, None
    for c in candidates:
        score = overlap(text, c)
        if score > best:
            best, best_text = score, c
    return best, best_text
