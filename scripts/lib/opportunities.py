"""Record and compare demand-backed first-party interventions, including cold starts."""
from __future__ import annotations
import hashlib
from datetime import date
from pathlib import Path
from . import dataforseo


def assess(candidates, *, today=None, root=None):
    today = today or date.today()
    if not isinstance(candidates, list) or not 2 <= len(candidates) <= 10:
        raise ValueError('compare two to ten candidates, including improving an existing page')
    seen, ranked = set(), []
    for row in candidates:
        row = dict(row)
        if not row.get('id') or row['id'] in seen:
            raise ValueError('unique candidate IDs required')
        seen.add(row['id'])
        for key in ('query', 'audience', 'intent', 'page', 'original_value', 'business_reason', 'action'):
            if not isinstance(row.get(key), str) or len(row[key].strip()) < (1 if key == 'page' else 3):
                raise ValueError(f'candidate requires {key}')
        if not row['page'].startswith('/') or row['page'].startswith('//'):
            raise ValueError('candidate page must be site-relative')
        evidence = row.get('evidence', [])
        valid = []
        for e in evidence:
            if e.get('kind') not in ('gsc', 'customer_question', 'serp', 'keyword_data') or not e.get('reference') or not e.get('observation'):
                continue
            observed = date.fromisoformat(e['observed_on'])
            if 0 <= (today-observed).days <= 90:
                evidence = {**e, 'provenance_kind': 'operator_supplied_assertion'}
                if e.get('snapshot') and root:
                    path = (Path(root) / e['snapshot']).resolve()
                    if not path.is_relative_to(Path(root).resolve()) or not path.is_file():
                        raise ValueError('evidence snapshot must exist inside the repo')
                    evidence.update(provenance_kind='local_snapshot_not_automatically_verified',
                                    snapshot_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                valid.append(evidence)
        value, effort = row.get('business_value'), row.get('effort_hours')
        if type(value) is not int or not 1 <= value <= 3 or not isinstance(effort, (float,int)) or effort <= 0:
            raise ValueError('business_value is 1..3; effort_hours must be positive')
        ready = bool(valid) and len(row['original_value']) >= 30 and len(row['business_reason']) >= 30
        row.update(status='ready_for_editorial_selection' if ready else 'needs_evidence',
                   priority=value if ready else None,
                   priority_basis='operator ordinal business value, then lower estimated effort; not forecast traffic',
                   accepted_evidence=valid)
        ranked.append(row)
    ranked.sort(key=lambda r: (r['priority'] is None, -(r['priority'] or 0), r['effort_hours'], r['id']))
    return {'kind': 'demand_assessment', 'assessed_on': today.isoformat(), 'candidates': ranked,
            'suggested_id': next((r['id'] for r in ranked if r['priority'] is not None), None),
            'limitations': 'Evidence references and business judgments require inspection; scores do not predict traffic.'}


def discover(cfg, queries, location, language):
    """Explicit opt-in paid queries; retain raw responses and failures, never invent volume."""
    if not 1 <= len(queries) <= 10:
        raise ValueError('use one to ten seed queries to bound paid calls')
    result = {'queries': [], 'location_code': location, 'language_code': language, 'observed_on': date.today().isoformat()}
    try:
        raw = dataforseo.search_volume(cfg, queries, location)
        volumes = {r['keyword']: r.get('search_volume') for r in (raw['tasks'][0].get('result') or [])}
        result['volume_response'] = raw
    except Exception as exc:
        volumes = {}; result['volume_error'] = str(exc)[:200]
    for q in queries:
        row = {'query': q, 'monthly_searches': volumes.get(q)}
        try:
            raw = dataforseo.serp_live(cfg, q, location, language)
            dataforseo._check(raw, 'seed-discovery')
            row['serp_response'] = raw
            if not raw.get('tasks') or any(not t.get('result') for t in raw['tasks']):
                row['serp_error'] = 'No completed SERP result returned'

        except Exception as exc: row['serp_error'] = str(exc)[:200]
        result['queries'].append(row)
    result['complete'] = 'volume_error' not in result and all('serp_response' in r and 'serp_error' not in r for r in result['queries'])
    return result
