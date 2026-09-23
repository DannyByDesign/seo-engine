"""Comparable observed traffic reports; no causal or citation-to-visit inference."""
from __future__ import annotations
import hashlib
import json
import math
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import urlsplit

METRICS = ('sessions', 'key_events')


def channel(source, medium):
    source, medium = source.lower().strip(), medium.lower().strip()
    if source == 'google' and medium == 'organic':
        return 'google_organic'
    host = urlsplit(source if '://' in source else 'https://' + source).hostname or ''
    if any(host == h or host.endswith('.' + h) for h in ('chatgpt.com', 'chat.openai.com')) and medium not in ('cpc', 'ppc', 'paid', 'paid_social'):
        return 'chatgpt_referral'
    return 'other'


def validate(data, today=None):
    today = today or date.today()
    for key in ('property', 'timezone', 'exporter', 'site_url'):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f'traffic export requires {key}')
    ZoneInfo(data['timezone'])
    start, end = date.fromisoformat(data['start']), date.fromisoformat(data['end'])
    if start > end or end > today - timedelta(days=3):
        raise ValueError('traffic windows must be ordered and at least three days old')
    if data.get('complete') is not True or data.get('sampled') or data.get('thresholded'):
        raise ValueError('incomplete, sampled or thresholded exports cannot support outcome decisions')
    if not isinstance(data.get('synthetic'), bool):
        raise ValueError('explicit synthetic boolean required')
    seen = set()
    for row in data['rows']:
        day = date.fromisoformat(row['date'])
        if not start <= day <= end:
            raise ValueError('row outside declared coverage')
        page = row['page']
        if not page.startswith('/') or page.startswith('//'):
            raise ValueError('page must be a site-relative path')
        key = (row['date'], page, row['source'], row['medium'])
        if key in seen:
            raise ValueError('duplicate traffic row')
        seen.add(key)
        for metric in METRICS:
            number = row[metric]
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0:
                raise ValueError(f'invalid {metric}')
    return data


def read_export(path):
    path = Path(path)
    data = validate(json.loads(path.read_text()))
    return {**data, 'provenance': {'file': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}


def totals(data, pages):
    result = {c: {m: 0 for m in METRICS} for c in ('google_organic', 'chatgpt_referral')}
    for row in data['rows']:
        c = channel(row['source'], row['medium'])
        if c in result and row['page'].split('?')[0] in pages:
            for metric in METRICS:
                result[c][metric] += row[metric]
    return result


def compare(before, after, pages, deployed_on, controls=(), minimum_sessions=100):
    validate(before); validate(after)
    if set(pages) & set(controls):
        raise ValueError('treatment and control pages must be disjoint')
    if not pages:
        raise ValueError('at least one treatment page required')
    for key in ('property', 'timezone', 'site_url', 'exporter', 'filters', 'synthetic'):
        if before.get(key) != after.get(key):
            raise ValueError(f'incomparable {key}')
    bs, be, ads, ae = [date.fromisoformat(v) for v in (before['start'], before['end'], after['start'], after['end'])]
    deployed = date.fromisoformat(deployed_on)
    days = (be-bs).days+1
    if days != (ae-ads).days+1 or days < 14 or days % 7 or bs.weekday() != ads.weekday():
        raise ValueError('use equal windows of at least two whole weeks with matching weekdays')
    if not be < deployed < ads:
        raise ValueError('deployment must fall strictly between baseline and post windows')
    b, a = totals(before, pages), totals(after, pages)
    cb, ca = totals(before, controls), totals(after, controls)
    results = {}
    for c in b:
        delta = a[c]['sessions'] - b[c]['sessions']
        enough = min(a[c]['sessions'], b[c]['sessions']) >= max(100, minimum_sessions)
        results[c] = {'before': b[c], 'after': a[c], 'session_delta': delta,
                      'relative_change': delta/b[c]['sessions'] if b[c]['sessions'] else None,
                      'decision': ('observed_new_traffic' if b[c]['sessions'] == 0 and a[c]['sessions'] >= max(100, minimum_sessions) else 'review_observed_change' if enough else 'insufficient_sample'),
                      'causal_lift': None}
        if controls:
            results[c]['controls'] = {'before': cb[c], 'after': ca[c]}
            results[c]['difference_in_differences'] = delta - (ca[c]['sessions']-cb[c]['sessions'])
            results[c]['control_caveat'] = 'Descriptive only; parallel trends and comparability not established.'
    return {'kind': 'observed_traffic_comparison', 'synthetic': before['synthetic'], 'days_per_window': days,
            'pages': sorted(pages), 'channels': results,
            'provenance': [before.get('provenance'), after.get('provenance')],
            'limitations': ['Not causal proof; seasonality, brand demand and other changes may explain movement.',
                           'Missing referrers, consent and blockers can hide visits; API probes are not traffic.',
                           'Key events reflect the property configuration, not necessarily qualified leads.']}
