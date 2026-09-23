"""Review receipts bind explicit editorial judgment to exact content and evidence.

These receipts record accountable review, not an automated proof of truth. Numeric
presence and quote matching alone cannot establish that a source supports a claim.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from . import article, publication, pubstate


def plain(text: str) -> str:
    return re.sub(r'\s+', ' ', BeautifulSoup(publication.render_markdown(text), 'lxml').get_text(' ', strip=True)).strip()


def digest(meta: dict, body: str, root: Path) -> str:
    metadata = {k: v for k, v in meta.items() if k not in ('editorial_review', 'status', 'published_at', 'updated_at', 'gate_overridden')}
    files = {}
    for source in (meta.get('research') or {}).get('sources', []):
        path = Path(str(source.get('cache') or ''))
        files[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    asset_dir = root / 'assets' / publication.asset_name(meta, str(meta.get('slug') or 'unassigned'))
    paths = list(asset_dir.rglob('*')) if asset_dir.is_dir() else []
    for path in [root / 'site.yml', root / 'strategy.yml', *paths]:
        if path.is_file():
            files[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    payload = json.dumps({'meta': metadata, 'body': body, 'files': files}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def review_problems(meta: dict, body: str, root: Path, review: dict) -> list[str]:
    problems = []
    for field in ('reviewer', 'reader_need', 'value_added'):
        if len(str(review.get(field) or '').strip()) < (3 if field == 'reviewer' else 30):
            problems.append(f'editorial review needs {field}')
    if review.get('facts_checked') is not True:
        problems.append('reviewer must explicitly attest facts_checked after checking all factual claims')
    claims = review.get('claims')
    if not isinstance(claims, list) or not claims:
        return problems + ['review needs claim-to-source assessments']
    text = plain(body).lower()
    sources = {s.get('url'): s for s in (meta.get('research') or {}).get('sources', [])}
    covered_numbers = set()
    for i, claim in enumerate(claims):
        if not isinstance(claim, dict):
            problems.append(f'claim {i} must be an object'); continue
        words = plain(str(claim.get('claim') or '')).lower()
        source = sources.get(claim.get('source'))
        path = Path(str((source or {}).get('cache') or ''))
        quote = re.sub(r'\s+', ' ', str(claim.get('quote') or '')).strip().lower()
        source_text = re.sub(r'\s+', ' ', path.read_text()).lower() if path.is_file() else ''
        if not words or words not in text:
            problems.append(f'claim {i} is not present in the final body')
        if not quote or quote not in source_text:
            problems.append(f'claim {i} quotation is not in its fetched source')
        if len(str(claim.get('assessment') or '').strip()) < 30:
            problems.append(f'claim {i} needs a contextual assessment of entity, metric, period and caveats')
        covered_numbers.update(article.numbers_in(words))
    missing = article.numbers_in(text) - covered_numbers
    if missing:
        problems.append(f'numbers not covered by claim assessments: {sorted(missing)}')
    return problems


def record_review(meta: dict, body: str, root: Path, review: dict) -> dict:
    if not meta.get('author'):
        pub = publication.load_publication(root)
        meta['author'] = meta.get('original_author') or next(iter(pub.authors), '')
    problems = review_problems(meta, body, root, review)
    if not meta.get('author'):
        problems.append('an accountable author must be assigned before review')
    if problems:
        raise ValueError('; '.join(problems))
    return {**review, 'kind': 'accountable_editorial_review', 'reviewed_at': pubstate.now_iso(),
            'digest': digest(meta, body, root)}


def valid_review(meta: dict, body: str, root: Path) -> bool:
    review = meta.get('editorial_review') or {}
    return bool(review.get('digest') == digest(meta, body, root)
                and not review_problems(meta, body, root, review))
