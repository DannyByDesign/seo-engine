"""Terminal research collection with bounded paid calls and durable source receipts."""
from __future__ import annotations

import fcntl
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4

from . import brave, dataforseo, firecrawl, http_util, pubstate

OPERATIONS = {'dataforseo': ('serp', 'volume', 'ideas', 'competitors', 'ranked-keywords'),
              'brave': ('search',), 'firecrawl': ('search', 'scrape')}


def collect(cfg, provider, operation, *, query=None, target=None, location=2840,
            language='en', country='US', limit=10, allow_paid=False, search_location=None):
    if operation not in OPERATIONS.get(provider, ()):
        raise ValueError('unsupported provider/operation combination')
    if not allow_paid: raise ValueError('paid/quota-consuming research needs --allow-paid under existing authorization')
    if type(limit) is not int or not 1 <= limit <= 20: raise ValueError('limit must be 1..20')
    configured = provider == 'firecrawl' or cfg.integration_available(provider if provider != 'brave' else 'brave_search')
    if operation in ('serp', 'volume', 'ideas', 'search') and (not isinstance(query, str) or not query.strip()):
        raise ValueError('this operation needs an agent-derived query')
    if operation in ('competitors', 'ranked-keywords') and (not isinstance(target, str) or not re.fullmatch(r'[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', target)):
        raise ValueError('domain research needs a bare target domain')
    if operation == 'scrape':
        url = urlsplit(target or '')
        if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password:
            raise ValueError('scrape needs an absolute public source URL without credentials')
    now = datetime.now(timezone.utc)
    policy = (cfg.site.get('growth') or {}).get('research') or {}
    cap = policy.get('daily_call_limit', 20)
    if type(cap) is not int or not 1 <= cap <= 1000: raise ValueError('growth.research.daily_call_limit must be 1..1000')
    state = cfg.state_dir / 'research'; state.mkdir(exist_ok=True)
    with (state / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        budget_path = state / f'calls-{now.date()}.json'
        budget = json.loads(budget_path.read_text()) if budget_path.exists() else {'attempts': 0}
        if budget['attempts'] >= cap: raise ValueError('daily research call limit reached; reuse evidence or wait for next UTC day')
        if configured:
            budget['attempts'] += 1
            pubstate.save_json(budget_path, budget)
    result = {'provider': provider, 'operation': operation, 'query': query, 'target': target,
              'location_code': location, 'language': language, 'country': country, 'limit': limit,
              'observed_on': now.date().isoformat(), 'collected_at': now.isoformat(),
              'complete': False, 'synthetic': False, 'cost_usd': None}
    result['requested_locale'] = {'location_code': location, 'country': country, 'language': language, 'search_location': search_location}
    result['applied_locale'] = {}
    result['unsupported_locale'] = []
    try:
        if not configured: raise ValueError(f'{provider} credentials missing; run check_integrations.py for exact setup')
        if provider == 'brave':
            result['applied_locale'] = {'country': country, 'search_lang': language}
            result['unsupported_locale'] = ['location_code', 'search_location']
            result['source_url'] = brave.BASE_URL
            raw = brave.search(cfg, query, country, language, limit)
            result['complete'] = True
            result['scope'] = 'Brave web index; not Google positions or consumer ChatGPT visibility'
        elif provider == 'firecrawl':
            result['source_url'] = firecrawl.BASE_URL + '/' + operation
            if operation == 'search':
                result['applied_locale'] = {'country': country}
                if search_location: result['applied_locale']['location'] = search_location
                result['unsupported_locale'] = ['location_code', 'language']
                raw = firecrawl.search_raw(cfg, query, limit, country=country, location=search_location)
            else:
                result['unsupported_locale'] = ['location_code', 'country', 'language', 'search_location']
                raw = firecrawl.scrape(cfg, target, formats=['markdown'])
            result['complete'] = raw.get('success') is True and 'data' in raw
            result['anonymous'] = not cfg.has('FIRECRAWL_API_KEY')
        else:
            result['applied_locale'] = {'location_code': location}
            result['unsupported_locale'] = ['country', 'search_location']
            if operation != 'volume': result['applied_locale']['language_code'] = language
            else: result['unsupported_locale'].append('language')
            paths = {'serp': '/serp/google/organic/live/advanced', 'volume': '/keywords_data/google_ads/search_volume/live',
                     'ideas': '/dataforseo_labs/google/keyword_ideas/live', 'competitors': '/dataforseo_labs/google/competitors_domain/live',
                     'ranked-keywords': '/dataforseo_labs/google/ranked_keywords/live'}
            result['source_url'] = dataforseo.BASE_URL + paths[operation]
            if operation == 'serp': raw = dataforseo.serp_live(cfg, query, location, language)
            elif operation == 'volume': raw = dataforseo.search_volume(cfg, [query], location)
            elif operation == 'ideas': raw = dataforseo.keyword_ideas(cfg, [query], location, language, limit)
            elif operation == 'competitors': raw = dataforseo.competitors_domain(cfg, target, location, limit, language)
            else: raw = dataforseo.ranked_keywords(cfg, target, location, language, limit)
            result['complete'] = bool(raw.get('tasks')) and all(t.get('status_code') == 20000 and t.get('result') is not None for t in raw['tasks'])
            result['cost_usd'] = raw.get('cost')
            result['scope'] = 'Provider-observed SERPs or modeled keyword/domain estimates, not actual website visits'
        result['response'] = raw
        if not result['complete']: result['error'] = 'No completed provider result; do not infer no demand'
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
        result['error'] = http_util.sanitize_text(str(exc))
    text = json.dumps(result, ensure_ascii=False)
    for key, value in cfg.env.items():
        if value and len(value) >= 4 and any(part in key for part in ('KEY', 'TOKEN', 'PASSWORD', 'SECRET')):
            text = text.replace(json.dumps(value, ensure_ascii=False)[1:-1], 'REDACTED')
    result = json.loads(text)
    path = cfg.reports_dir / 'research' / f'{now.strftime("%Y%m%dT%H%M%S")}-{uuid4().hex}.json'
    pubstate.save_json(path, result)
    return {'checked': result['complete'], 'output': str(path), 'result': result}


def summary(receipt):
    """Keep the actual response in the artifact, not in the agent's context window."""
    result = {k: v for k, v in receipt['result'].items() if k != 'response'}
    raw = receipt['result'].get('response', {})
    data = raw.get('data', {}) if isinstance(raw, dict) else {}
    preview = data.get('markdown') if isinstance(data, dict) else None
    if preview is None: preview = json.dumps(raw, ensure_ascii=False)
    result.update(preview=preview[:3000], preview_truncated=len(preview) > 3000,
                  response_bytes=len(json.dumps(raw).encode()),
                  next_step='Inspect relevant fields in the saved JSON. Prefer response.data.markdown over rawHtml; do not print whole large responses.')
    return {**receipt, 'result': result}
