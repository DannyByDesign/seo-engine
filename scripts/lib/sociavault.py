"""SociaVault client — public social-media data (Reddit, X, TikTok, YouTube,
Instagram, Google) for conversation and trend monitoring. Optional.

Why it is here: the youngest audiences ask their questions in TikTok
comments, Reddit threads and X replies before they ask a search box. The
Curate layer (pub-curate's seers.py `social_trend` provider and
score_suggestions.py's `social` signal) reads those conversations to find
topics worth an article while they are still forming.

API facts (from docs.sociavault.com, verified against its OpenAPI spec):
  base    https://api.sociavault.com/v1
  auth    header `X-API-Key: sk_live_...`
  cost    1 credit per request on the endpoints used here (transcripts with
          the AI fallback cost 10); credits never expire; no rate limits
  shape   {"success": true, "data": {...}, "credits_used": 1, "credits_remaining": N}
          Collections inside `data` are often index-keyed OBJECTS
          ({"0": {...}, "1": {...}}) rather than arrays — `_as_list` folds both.

Every helper returns raw vendor JSON; `normalize()` maps each platform's
item into one post shape so downstream code never touches vendor fields.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from . import http_util
from .config import Config

BASE_URL = "https://api.sociavault.com/v1"
_HINT = "Get a key at sociavault.com/dashboard (50 free credits; pay-as-you-go after)."

DEFAULT_PLATFORMS = ("reddit", "twitter", "tiktok", "youtube")

_RECENCY = {
    "reddit": {"day": "day", "week": "week", "month": "month"},
    "tiktok": {"day": "yesterday", "week": "this-week", "month": "this-month"},
    "youtube": {"day": "today", "week": "this_week", "month": "this_month"},
    "instagram": {"day": "last-day", "week": "last-week", "month": "last-month"},
    "google": {"day": "last-day", "week": "last-week", "month": "last-month"},
}


class SociaVaultError(RuntimeError):
    """The API reported success=false inside an HTTP 200, or malformed data."""


def _headers(cfg: Config) -> dict[str, str]:
    return {"X-API-Key": cfg.require("SOCIAVAULT_API_KEY", _HINT)}


def _get(cfg: Config, path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
    resp = http_util.get(
        f"{BASE_URL}{path}", headers=_headers(cfg), params=clean,
        min_interval=0.3, timeout=90.0, check=True,
    )
    data = resp.json()
    if isinstance(data, dict) and data.get("success") is False:
        raise SociaVaultError(f"{path}: {data.get('error') or data.get('message') or 'success=false'}")
    return data if isinstance(data, dict) else {"data": data}


def _as_list(value: Any) -> list[Any]:
    """Fold SociaVault's index-keyed objects ({"0": ..}) and plain arrays."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        keys = list(value.keys())
        if keys and all(str(k).isdigit() for k in keys):
            return [value[k] for k in sorted(keys, key=lambda k: int(k))]
    return []


def _items(payload: dict[str, Any], *keys: str) -> list[Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    for key in keys:
        found = _as_list((data or {}).get(key))
        if found:
            return found
    return []


def _iso(value: Any) -> Optional[str]:
    if value in (None, "", 0):
        return None
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
            return datetime.fromtimestamp(int(float(value)), tz=timezone.utc).isoformat()
        return str(value)
    except (ValueError, OSError, OverflowError):
        return None


def credits(cfg: Config) -> dict[str, Any]:
    return _get(cfg, "/credits")


def reddit_search(cfg: Config, query: str, *, sort: str = "relevance", timeframe: str = "week",
                  after: Optional[str] = None, trim: bool = True) -> dict[str, Any]:
    return _get(cfg, "/scrape/reddit/search",
                {"query": query, "sort": sort, "timeframe": timeframe, "after": after, "trim": str(trim).lower()})


def reddit_subreddit(cfg: Config, subreddit: str, *, sort: str = "hot", timeframe: str = "week",
                     after: Optional[str] = None, trim: bool = True) -> dict[str, Any]:
    return _get(cfg, "/scrape/reddit/subreddit",
                {"subreddit": subreddit.removeprefix("r/"), "sort": sort, "timeframe": timeframe,
                 "after": after, "trim": str(trim).lower()})


def twitter_search(cfg: Config, query: str, *, kind: str = "Latest",
                   cursor: Optional[str] = None) -> dict[str, Any]:
    return _get(cfg, "/scrape/twitter/search", {"query": query, "type": kind, "cursor": cursor})


def tiktok_search(cfg: Config, query: str, *, date_posted: str = "this-week", sort_by: str = "relevance",
                  region: Optional[str] = None, cursor: Optional[int] = None, trim: bool = True) -> dict[str, Any]:
    return _get(cfg, "/scrape/tiktok/search/keyword",
                {"query": query, "date_posted": date_posted, "sort_by": sort_by, "region": region,
                 "cursor": cursor, "trim": str(trim).lower()})


def tiktok_trending(cfg: Config, region: str = "US", *, trim: bool = True) -> dict[str, Any]:
    return _get(cfg, "/scrape/tiktok/trending", {"region": region, "trim": str(trim).lower()})


def youtube_search(cfg: Config, query: str, *, upload_date: str = "this_week", sort_by: str = "relevance",
                   region: Optional[str] = None, continuation: Optional[str] = None) -> dict[str, Any]:
    return _get(cfg, "/scrape/youtube/search",
                {"query": query, "uploadDate": upload_date, "sortBy": sort_by, "region": region,
                 "continuationToken": continuation})


def instagram_hashtag(cfg: Config, hashtag: str, *, date_posted: str = "last-week", media_type: str = "all",
                      cursor: Optional[str] = None) -> dict[str, Any]:
    return _get(cfg, "/scrape/instagram/search/hashtag",
                {"hashtag": hashtag.lstrip("#"), "date_posted": date_posted, "media_type": media_type,
                 "cursor": cursor})


def google_search(cfg: Config, query: str, *, region: Optional[str] = None,
                  date_posted: Optional[str] = "last-week", page: Optional[int] = None) -> dict[str, Any]:
    return _get(cfg, "/scrape/google/search",
                {"query": query, "region": region, "date_posted": date_posted, "page": page})


def youtube_transcript(cfg: Config, url: str) -> dict[str, Any]:
    return _get(cfg, "/scrape/youtube/video/transcript", {"url": url})


def tiktok_transcript(cfg: Config, url: str, *, language: str = "en", ai_fallback: bool = False) -> dict[str, Any]:
    return _get(cfg, "/scrape/tiktok/transcript",
                {"url": url, "language": language, "use_ai_as_fallback": str(ai_fallback).lower()})


def _first(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return default


def normalize(platform: str, item: dict[str, Any]) -> dict[str, Any]:
    """One post shape for every platform: platform, id, url, title, text,
    author, community, score, comments, views, created_at."""
    if not isinstance(item, dict):
        return {"platform": platform, "text": str(item)}
    if platform == "reddit":
        sub = item.get("subreddit")
        if isinstance(sub, dict):
            sub = sub.get("name")
        permalink = item.get("permalink") or ""
        url = item.get("url") if str(item.get("url") or "").startswith("http") else ""
        if permalink and permalink.startswith("/"):
            url = "https://www.reddit.com" + permalink
        return {
            "platform": "reddit", "id": _first(item, "id", "name", "post_id"), "url": url or item.get("url"),
            "title": item.get("title"), "text": _first(item, "selftext", "body", default=""),
            "author": item.get("author") if not isinstance(item.get("author"), dict) else item["author"].get("name"),
            "community": f"r/{sub}" if sub else None,
            "score": _first(item, "score", "ups", "upvotes", default=0),
            "comments": _first(item, "num_comments", "comment_count", "comments", default=0),
            "views": None, "created_at": _iso(_first(item, "created_utc", "created", "created_at_iso")),
        }
    if platform == "tiktok":
        info = item.get("aweme_info") if isinstance(item.get("aweme_info"), dict) else item
        stats = info.get("statistics") or {}
        author = info.get("author") or {}
        return {
            "platform": "tiktok", "id": _first(info, "aweme_id", "id"),
            "url": _first(info, "share_url", "url") or (
                f"https://www.tiktok.com/@{author.get('unique_id')}/video/{info.get('aweme_id')}"
                if author.get("unique_id") and info.get("aweme_id") else None),
            "title": None, "text": info.get("desc", ""),
            "author": _first(author, "nickname", "unique_id"), "community": None,
            "score": stats.get("digg_count", 0), "comments": stats.get("comment_count", 0),
            "views": stats.get("play_count"), "created_at": _iso(info.get("create_time")),
        }
    if platform == "youtube":
        channel = item.get("channel") or {}
        return {
            "platform": "youtube", "id": item.get("id"), "url": item.get("url"),
            "title": item.get("title"), "text": item.get("description", ""),
            "author": _first(channel, "title", "handle"), "community": None,
            "score": None, "comments": None, "views": item.get("viewCountInt"),
            "created_at": item.get("publishedTimeText"),
        }
    if platform == "twitter":
        user = item.get("user") or item.get("author") or {}
        handle = _first(user, "screen_name", "username", "handle")
        tid = _first(item, "id_str", "id", "rest_id")
        return {
            "platform": "twitter", "id": tid,
            "url": item.get("url") or (f"https://x.com/{handle}/status/{tid}" if handle and tid else None),
            "title": None, "text": _first(item, "full_text", "text", default=""),
            "author": handle or _first(user, "name"), "community": None,
            "score": _first(item, "favorite_count", "likes", "like_count", default=0),
            "comments": _first(item, "reply_count", "replies", default=0),
            "views": _first(item, "views_count", "view_count"),
            "created_at": item.get("created_at"),
        }
    if platform == "instagram":
        owner = item.get("owner") or {}
        return {
            "platform": "instagram", "id": _first(item, "id", "shortcode"), "url": item.get("url"),
            "title": None, "text": item.get("caption", ""),
            "author": _first(owner, "username"), "community": item.get("hashtag"),
            "score": _first(item, "like_count", "likes", default=None),
            "comments": _first(item, "comment_count", "comments", default=None),
            "views": _first(item, "video_play_count", "play_count"), "created_at": _iso(item.get("taken_at")),
        }
    if platform == "google":
        return {
            "platform": "google", "id": None, "url": item.get("url"), "title": item.get("title"),
            "text": item.get("description", ""), "author": None, "community": None,
            "score": None, "comments": None, "views": None, "created_at": None,
        }
    return {"platform": platform, "text": str(item)[:500]}


def search_conversations(
    cfg: Config, query: str, *, platforms: tuple[str, ...] = DEFAULT_PLATFORMS,
    recency: str = "week", limit: int = 20,
) -> dict[str, Any]:
    """Fan one query out across platforms and return normalized posts.
    A platform failure lands in `errors` (sanitized) and never aborts the
    others — a partial read is still a read."""
    posts: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    credits_used = 0
    for platform in platforms:
        try:
            if platform == "reddit":
                payload = reddit_search(cfg, query, timeframe=_RECENCY["reddit"][recency])
                raw = _items(payload, "posts", "results")
            elif platform == "twitter":
                payload = twitter_search(cfg, query, kind="Latest")
                raw = _items(payload, "tweets", "results", "items", "timeline")
            elif platform == "tiktok":
                payload = tiktok_search(cfg, query, date_posted=_RECENCY["tiktok"][recency])
                raw = _items(payload, "search_item_list", "items", "videos")
            elif platform == "youtube":
                payload = youtube_search(cfg, query, upload_date=_RECENCY["youtube"][recency])
                raw = _items(payload, "videos", "results", "items")
            elif platform == "instagram":
                payload = instagram_hashtag(cfg, query.replace(" ", ""), date_posted=_RECENCY["instagram"][recency])
                raw = _items(payload, "posts", "items")
            elif platform == "google":
                payload = google_search(cfg, query, date_posted=_RECENCY["google"][recency])
                raw = _items(payload, "results", "items")
            else:
                errors[platform] = "unsupported platform"
                continue
            credits_used += int(payload.get("credits_used") or 0)
            posts.extend(normalize(platform, item) for item in raw[:limit])
        except Exception as exc:
            errors[platform] = http_util.sanitize_text(str(exc))[:300]
    return {"query": query, "recency": recency, "posts": posts, "errors": errors,
            "credits_used": credits_used}
