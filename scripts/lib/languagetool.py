"""LanguageTool editing reports via an authenticated API or an owned HTTP server."""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlsplit
from uuid import uuid4

from bs4 import BeautifulSoup
from . import http_util, publication, pubstate

PAID_URL = 'https://api.languagetoolplus.com/v2/check'


def endpoint(cfg):
    url = str(cfg.get('LANGUAGETOOL_URL') or '').strip()
    if not url:
        raise ValueError('Set LANGUAGETOOL_URL to an owned /v2/check server or the authenticated API; the public API forbids automation')
    parsed = urlsplit(url)
    if parsed.hostname == 'api.languagetool.org':
        raise ValueError('The public LanguageTool API forbids automated requests; use an owned server or authenticated API')
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.path.endswith('/v2/check'):
        raise ValueError('LANGUAGETOOL_URL must be an absolute /v2/check endpoint without credentials, query or fragment')
    if parsed.scheme != 'https' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Use HTTPS for a remote LanguageTool server')
    if parsed.hostname == 'api.languagetoolplus.com' and url != PAID_URL:
        raise ValueError('Use the documented authenticated LanguageTool endpoint')
    return url


def prose(source, format='markdown'):
    """Check reader-visible prose, not frontmatter, code, URLs or hidden HTML."""
    if format == 'text': return source.strip()
    if format == 'markdown':
        _, source = publication.parse_frontmatter(source)
        source = publication.render_markdown(source)
    elif format != 'html': raise ValueError('format must be markdown, html or text')
    soup = BeautifulSoup(source, 'lxml')
    for node in soup.select('pre, code, script, style, noscript, template, [hidden], [aria-hidden="true"]'):
        node.decompose()
    for node in soup.select('address, article, aside, blockquote, br, dd, div, dl, dt, figcaption, footer, h1, h2, h3, h4, h5, h6, header, hr, li, main, nav, ol, p, section, table, td, th, tr, ul'):
        node.insert_before('\n\n')
        node.insert_after('\n\n')
    text = re.sub(r'[^\S\n]+', ' ', soup.get_text())
    text = re.sub(r' *\n *', '\n', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def chunks(text, limit):
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            boundary = text.rfind(' ', start, end)
            if boundary > start: end = boundary + 1
        yield start, text[start:end]
        start = end


def character_index(text, offset):
    if type(offset) is not int or offset < 0: raise ValueError('Invalid LanguageTool offset')
    encoded = text.encode('utf-16-le')
    if offset * 2 > len(encoded): raise ValueError('LanguageTool offset exceeds checked text')
    return len(encoded[:offset * 2].decode('utf-16-le'))


def check(cfg, source, *, format='markdown', language=None, level=None):
    report = {'provider': 'LanguageTool', 'checked': False, 'created_at': pubstate.now_iso(),
              'source_sha256': hashlib.sha256(source.encode()).hexdigest(), 'format': format,
              'matches': [], 'completed_chunks': 0, 'checked_characters': 0,
              'coverage': 'Submitted content only; Markdown frontmatter, code and hidden HTML are excluded. Check titles and summaries separately as text.',
              'interpretation': 'Suggestions need editorial judgment. No matches does not establish factuality, originality or good writing.'}
    try:
        text = prose(source, format)
        report.update(checked_text=text, text_sha256=hashlib.sha256(text.encode()).hexdigest(), characters=len(text))
        if not text: raise ValueError('No prose to check')
        url = endpoint(cfg)
        report['endpoint'] = url
        language = language or cfg.get('LANGUAGETOOL_LANGUAGE') or 'en-US'
        level = level or cfg.get('LANGUAGETOOL_LEVEL') or 'default'
        if level not in ('default', 'picky'): raise ValueError('LanguageTool level must be default or picky')
        form = {'language': language, 'level': level}
        if language == 'auto':
            variants = cfg.require('LANGUAGETOOL_PREFERRED_VARIANTS', 'Set variants such as en-US,de-DE for automatic language detection')
            form['preferredVariants'] = variants
        if cfg.get('LANGUAGETOOL_DISABLED_RULES'): form['disabledRules'] = cfg.get('LANGUAGETOOL_DISABLED_RULES')
        if url == PAID_URL:
            form.update(username=cfg.require('LANGUAGETOOL_USERNAME', 'Use your API account email'),
                        apiKey=cfg.require('LANGUAGETOOL_API_KEY', 'Create a proofreading API access token'))
        limit = int(cfg.get('LANGUAGETOOL_CHUNK_CHARS') or 10000)
        if not 100 <= limit <= 10000: raise ValueError('LANGUAGETOOL_CHUNK_CHARS must be 100..10000')
        parts = list(chunks(text, limit))
        if len(parts) > 20: raise ValueError('More than 20 chunks; check smaller documents separately')
        report.update(language=language, level=level, chunk_count=len(parts),
                      disabled_rules=form.get('disabledRules', ''), preferred_variants=form.get('preferredVariants', ''),
                      offset_basis='Zero-based Python characters in checked_text; never source-file replacement offsets')
        for start, part in parts:
            response = http_util.post(url, data={**form, 'text': part}, retry='none', min_interval=3, timeout=45, check=True, allow_redirects=False)
            if response.status_code != 200: raise ValueError(f'LanguageTool returned HTTP {response.status_code}; redirects are not followed')
            raw = response.json()
            if not isinstance(raw, dict) or not isinstance(raw.get('matches'), list) or not isinstance(raw.get('language'), dict):
                raise ValueError('Malformed LanguageTool response')
            if raw.get('warnings', {}).get('incompleteResults'):
                raise ValueError('LanguageTool returned incomplete results; not a clean pass')
            for match in raw['matches']:
                if not isinstance(match, dict) or type(match.get('length')) is not int or match['length'] < 0:
                    raise ValueError('Malformed LanguageTool match')
                first = character_index(part, match['offset'])
                last = character_index(part, match['offset'] + match['length'])
                report['matches'].append({'offset': start + first, 'length': last - first, 'text': part[first:last],
                    'message': match['message'], 'replacements': [r['value'] for r in match.get('replacements', [])],
                    'rule': match.get('rule', {}), 'context': match.get('context', {}),
                    'chunk': report['completed_chunks']})
            report.update(software=raw.get('software', {}), detected_language=raw['language'])
            report['completed_chunks'] += 1
            report['checked_characters'] += len(part)
        report.update(checked=True, status='suggestions' if report['matches'] else 'no_matches')
    except (ValueError, KeyError, TypeError, AttributeError, OSError, RuntimeError) as exc:
        report.update(status='not_checked', error=http_util.sanitize_text(str(exc)))
    report['match_count'] = len(report['matches'])
    serialized = json.dumps(report, ensure_ascii=False)
    for key in ('LANGUAGETOOL_API_KEY', 'LANGUAGETOOL_USERNAME'):
        value = cfg.get(key)
        if value: serialized = serialized.replace(json.dumps(value, ensure_ascii=False)[1:-1], 'REDACTED')
    report = json.loads(serialized)
    path = cfg.reports_dir / 'writing' / f'languagetool-{uuid4().hex}.json'
    pubstate.save_json(path, report)
    return {k: report[k] for k in ('checked', 'status', 'source_sha256', 'match_count', 'completed_chunks', 'coverage')} | {'output': str(path), 'error': report.get('error')}
