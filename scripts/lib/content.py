"""Article-scoped research and operator permission, shared by both writing paths.

Only proposed publishable material belongs here. Raw interviews/private notes are
not imported. A confirmation records the operator's decision; it cannot prove one
occurred, so the host must obtain it before running the confirmation command.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from . import pubstate


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def required(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'content brief needs {name}')
    return value.strip()


def proposal(data, content_id):
    """Whitelist publishable fields; never carry a raw transcript to the writer."""
    if not isinstance(data, dict):
        raise ValueError('content proposal must be an object')
    result = {'content_id': required(content_id, 'content_id')}
    for key in ('topic', 'reader_intent', 'demand_evidence', 'unresolved', 'contribution', 'interview_summary'):
        result[key] = required(data.get(key), key)
    pages = data.get('competing_pages')
    if not isinstance(pages, list) or not pages:
        raise ValueError('content brief needs inspected competing_pages')
    result['competing_pages'] = []
    for page in pages:
        if not isinstance(page, dict):
            raise ValueError('competing page must be an object')
        row = {key: required(page.get(key), key) for key in ('url', 'coverage', 'gap')}
        if urlsplit(row['url']).scheme not in ('http', 'https') or not urlsplit(row['url']).hostname:
            raise ValueError('competing page needs an actual HTTP URL')
        result['competing_pages'].append(row)
    if data.get('mode') not in ('firsthand', 'external_only'):
        raise ValueError('choose firsthand or external_only after the topic interview')
    result['mode'] = data['mode']
    result['research_digest'] = str(data.get('research_digest') or '')
    constraints = data.get('constraints')
    if not isinstance(constraints, list) or not all(isinstance(x, str) for x in constraints):
        raise ValueError('constraints must list safe omission/positioning instructions, without private details')
    result['constraints'] = constraints
    result['items'] = []
    if not isinstance(data.get('items'), list):
        raise ValueError('items must be a list of proposed publishable evidence')
    for item in data.get('items', []):
        if not isinstance(item, dict):
            raise ValueError('interview evidence must be an object')
        row = {key: required(item.get(key), key) for key in ('id', 'text', 'kind', 'attribution', 'limits')}
        if row['kind'] not in ('experience', 'opinion', 'measurement'):
            raise ValueError('interview evidence must distinguish experience, opinion and measurement')
        result['items'].append(row)
    if len({i['id'] for i in result['items']}) != len(result['items']):
        raise ValueError('interview item IDs must be unique')
    if (result['mode'] == 'firsthand') != bool(result['items']):
        raise ValueError('firsthand needs evidence items; external_only must have none')
    return result


def record_path(root, content_id):
    return Path(root) / '.seo-engine/state/content' / (digest(content_id) + '.json')


def prepare(root, content_id, data):
    data = proposal(data, content_id)
    path = record_path(root, content_id)
    old = pubstate.load_json(path, {})
    if old.get('data') == data:
        return old  # An unchanged resume never discards permission.
    record = {'data': data, 'digest': digest(data), 'status': 'awaiting_confirmation'}
    pubstate.save_json(path, record)
    return record


def confirm(root, content_id, expected_digest, operator, statement):
    path = record_path(root, content_id)
    record = pubstate.load_json(path, {})
    if not record or digest(record['data']) != expected_digest or record['digest'] != expected_digest:
        raise ValueError('proposal changed; show the current proposed use to the operator')
    record.update(status='approved', approval={
        'operator': required(operator, 'operator'), 'statement': required(statement, 'explicit confirmation'),
        'digest': expected_digest, 'at': pubstate.now_iso()})
    pubstate.save_json(path, record)
    return reference(root, content_id, record)


def reference(root, content_id, record):
    return {'path': str(record_path(root, content_id).resolve()), 'digest': record['digest'], 'content_id': content_id}


def load(ref, content_id=None, root=None):
    if not isinstance(ref, dict) or not ref.get('path'):
        raise ValueError('awaiting_interview: record topic research and operator input first')
    if content_id is not None and ref.get('content_id') != content_id:
        raise ValueError('content permission belongs to another article/page')
    path = Path(ref['path'])
    if path.name != digest(ref.get('content_id')) + '.json' or path.parent.parts[-3:] != ('.seo-engine', 'state', 'content'):
        raise ValueError('invalid content permission location')
    if root is not None and path.resolve() != record_path(root, ref.get('content_id')).resolve():
        raise ValueError('content permission must be in this target workspace')
    record = pubstate.load_json(path, {})
    data = record.get('data') or {}
    if (record.get('status') != 'approved' or record.get('digest') != digest(data)
            or ref.get('digest') != record.get('digest')
            or (record.get('approval') or {}).get('digest') != record.get('digest')
            or data.get('content_id') != ref.get('content_id')):
        raise ValueError('awaiting_confirmation: missing, changed or revoked content permission')
    required(record['approval'].get('operator'), 'approving operator')
    required(record['approval'].get('statement'), 'explicit confirmation')
    return proposal(data, data['content_id'])


def source_text(source):
    if source.get('origin') == 'operator':
        return source.get('text', '')
    path = Path(str(source.get('cache') or ''))
    return path.read_text(encoding='utf-8') if path.is_file() else ''


def sources(data, start):
    return [{**item, 'index': start + n, 'id': 'interview:' + item['id'], 'url': '',
             'title': item['attribution'], 'origin': 'operator'}
            for n, item in enumerate(data['items'])]


def research_digest(research):
    return digest({'topic': research.get('topic'), 'plan': research.get('plan'), 'started_at': research.get('started_at'),
                   'sources': [{'url': s.get('url'), 'text': source_text(s)}
                               for s in research.get('sources', []) if s.get('origin') != 'operator']})


def publication_id(root, slug):
    return f'publication:{Path(root).name}:{slug}'


def check_article(meta, root, slug, repo_root=None):
    data = load(meta.get('content_brief'), publication_id(root, slug), repo_root)
    workspace = Path(meta['content_brief']['path']).resolve().parents[3]
    if not Path(root).resolve().is_relative_to(workspace):
        raise ValueError('content permission must belong to this publication workspace')
    if data['research_digest'] != research_digest(meta.get('research') or {}):
        raise ValueError('research changed; refresh the topic interview and proposed use')
    actual = [s for s in (meta.get('research') or {}).get('sources', []) if s.get('origin') == 'operator']
    expected = sources(data, 0)
    if [{k: v for k, v in s.items() if k != 'index'} for s in actual] != [
            {k: v for k, v in s.items() if k != 'index'} for s in expected]:
        raise ValueError('approved interview evidence changed; rerun article research')
    return data
