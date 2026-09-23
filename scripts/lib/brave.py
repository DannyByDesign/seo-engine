"""Brave Search API: web discovery, not Google rankings or keyword search volume."""
from . import http_util

BASE_URL = 'https://api.search.brave.com/res/v1/web/search'


def search(cfg, query, country='US', language='en', limit=10):
    if not query.strip() or not 1 <= limit <= 20:
        raise ValueError('Brave needs a query and limit 1..20')
    key = cfg.require('BRAVE_SEARCH_API_KEY', 'Create a Search API subscription/key at api-dashboard.search.brave.com.')
    response = http_util.get(BASE_URL, params={'q': query, 'country': country,
        'search_lang': language, 'count': limit, 'extra_snippets': 'true'},
        headers={'X-Subscription-Token': key, 'Accept': 'application/json'},
        check=True, retry='none', min_interval=1.0)
    raw = response.json()
    if not isinstance(raw, dict) or raw.get('error') or 'query' not in raw:
        raise ValueError('Brave returned an error or unrecognized search response')
    return raw
