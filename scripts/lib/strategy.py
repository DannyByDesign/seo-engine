"""Evidence-bound working memory for the host agent's growth reasoning.

The host agent does the research and writing. This module checks provenance and
handoffs; it does not mistake a valid JSON document for a good marketing decision.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from . import pubstate

SECTIONS = ('understand', 'research', 'position')
SKIP = {'.git', '.seo-engine', '.agents', '.claude', 'node_modules', '.venv', 'venv',
        'dist', 'build', '.next', '.nuxt', '__pycache__', 'vendor'}
TEXT = {'.md', '.mdx', '.html', '.json', '.js', '.jsx', '.ts', '.tsx', '.vue', '.svelte',
        '.astro', '.py', '.php', '.toml', '.yaml', '.yml', '.rb', '.go'}


def sha(value):
    return hashlib.sha256(value).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf-8')


def source_path(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('evidence/source path must be a file inside the target repository')
    if any(p.startswith('.env') or p in {'.git', 'credentials', 'secrets'} for p in Path(name).parts) or path.suffix in {'.pem', '.key'}:
        raise ValueError('secret files cannot be research evidence')
    return path


def inspect_repo(cfg):
    """Bounded inventory only: the agent chooses what to read, no secret contents emitted."""
    files, truncated = [], False
    engine = Path(__file__).resolve().parents[2]
    for base, dirs, names in os.walk(cfg.repo_root, followlinks=False):
        here = Path(base)
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.startswith('.')
                         and not (here / d).is_symlink() and (here / d).resolve() != engine
                         and not ((here / d) / 'scripts/lib/strategy.py').is_file())
        for name in sorted(names):
            path = here / name
            if path.is_symlink() or name.startswith('.') or path.suffix not in TEXT or path.stat().st_size > 500_000:
                continue
            if path.resolve().is_relative_to(engine) and cfg.repo_root.resolve() != engine:
                continue
            files.append(str(path.relative_to(cfg.repo_root)))
            if len(files) >= 500:
                truncated = True; break
        if truncated: break
    return {'repo_root': str(cfg.repo_root), 'files': files, 'truncated': truncated,
            'configured_site': cfg.site.get('site_url') or cfg.get('SEO_SITE_URL'),
            'integrations': cfg.available_integrations(),
            'instructions': 'Read relevant files, project instructions and live pages. Exclude the engine from business inference. Unknown frameworks are investigated, not rejected.'}


def nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be nonempty text')


def evidence_records(root, rows):
    if not isinstance(rows, list): raise ValueError('evidence must be a list')
    result = {}
    for row in rows:
        if not isinstance(row, dict): raise ValueError('each evidence item must be an object')
        for key in ('id', 'path', 'quote', 'kind'):
            nonempty(row.get(key), f'evidence.{key}')
        if row['id'] in result: raise ValueError('duplicate evidence id')
        if row['kind'] not in ('repo', 'web', 'api', 'customer', 'analytics'):
            raise ValueError('unsupported evidence kind')
        path = source_path(root, row['path'])
        raw = path.read_bytes()
        if row['quote'] not in raw.decode('utf-8'):
            raise ValueError(f"quotation absent from evidence {row['id']}")
        observed = date.fromisoformat(row.get('observed_on', ''))
        if not 0 <= (date.today() - observed).days <= 90:
            raise ValueError('evidence is future-dated or stale; inspect it again')
        if row['kind'] in ('web', 'api'):
            url = urlsplit(row.get('url', ''))
            if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
                raise ValueError('web/api evidence requires its actual source URL without credentials')
        result[row['id']] = {**row, 'sha256': sha(raw)}
    return result


def check_claims(claims, evidence):
    if not isinstance(claims, list) or not claims:
        raise ValueError('claims must distinguish sourced facts from hypotheses')
    for claim in claims:
        if not isinstance(claim, dict): raise ValueError('claim must be an object')
        nonempty(claim.get('text'), 'claim.text')
        if claim.get('kind') not in ('fact', 'hypothesis'):
            raise ValueError('claim.kind must be fact or hypothesis')
        refs = claim.get('evidence_ids', [])
        if not isinstance(refs, list) or any(ref not in evidence for ref in refs):
            raise ValueError('claim references unknown evidence')
        if claim['kind'] == 'fact' and not refs:
            raise ValueError('facts require evidence; otherwise label hypothesis')


def folder(cfg):
    return cfg.state_dir / 'strategy'


def load_valid(cfg, section):
    path = folder(cfg) / f'{section}.json'
    record = json.loads(path.read_text())
    if record['digest'] != sha(encoded({k: v for k, v in record.items() if k != 'digest'})):
        raise ValueError(f'{section} record changed outside the recorder')
    if record['repo_root'] != str(cfg.repo_root.resolve()):
        raise ValueError('strategy belongs to another repository')
    for parent, digest in record['parents'].items():
        if load_valid(cfg, parent)['digest'] != digest:
            raise ValueError(f'{section} depends on changed {parent}')
    for row in record['evidence'].values():
        if sha(source_path(cfg.repo_root, row['path']).read_bytes()) != row['sha256']:
            raise ValueError(f"changed evidence: {row['path']}")
        if (date.today() - date.fromisoformat(row['observed_on'])).days > 90:
            raise ValueError('stale research evidence')
    for name, digest in record.get('source_hashes', {}).items():
        if sha(source_path(cfg.repo_root, name).read_bytes()) != digest:
            raise ValueError(f'changed source dependency: {name}')
    return record


def save(cfg, section, data):
    if section not in SECTIONS: raise ValueError('unknown strategy section')
    if not isinstance(data, dict): raise ValueError('section input must be an object')
    nonempty(data.get('author'), 'author (agent identity is valid)')
    parents, evidence = {}, {}
    for parent in SECTIONS[:SECTIONS.index(section)]:
        record = load_valid(cfg, parent)
        parents[parent] = record['digest']; evidence.update(record['evidence'])
    own = evidence_records(cfg.repo_root, data.get('evidence', []))
    if set(own) & set(evidence): raise ValueError('use unique evidence IDs across sections')
    evidence.update(own)
    check_claims(data.get('claims'), evidence)
    required = {'understand': ('business', 'conversion_goal'),
                'research': ('market_summary',),
                'position': ('audience', 'problem', 'promise', 'differentiation')}[section]
    for key in required: nonempty(data.get(key), key)
    for key in {'understand': ('audiences', 'source_files', 'seed_queries'),
                'research': ('questions', 'competitors', 'opportunities'),
                'position': ('message_rules', 'copy_briefs')}[section]:
        if not isinstance(data.get(key), list) or not data[key]:
            raise ValueError(f'{key} must be a nonempty list')
    if not isinstance(data.get('unknowns'), list): raise ValueError('record unknowns explicitly (empty list allowed)')
    if section == 'understand':
        if not own: raise ValueError('understanding requires inspected repository evidence')
        for name in data['source_files']: source_path(cfg.repo_root, name)
        commands = data.get('commands', {})
        for key in ('test', 'build'):
            argv = commands.get(key)
            if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
                raise ValueError('record actual test/build argv; inspect an unknown stack rather than invent commands')
    elif section == 'research':
        if not any(e['kind'] in ('web', 'api', 'customer', 'analytics') for e in own.values()):
            raise ValueError('research requires external demand evidence, not just repository descriptions')
        from . import opportunities
        opportunities.assess(data['opportunities'], root=cfg.repo_root)
    else:
        for brief in data['copy_briefs']:
            for key in ('page', 'reader_job', 'angle', 'cta'):
                nonempty(brief.get(key), 'copy_brief.' + key)
            check_claims(brief.get('claims'), evidence)
    record = {'section': section, 'repo_root': str(cfg.repo_root.resolve()), 'created_at': pubstate.now_iso(),
              'parents': parents, 'evidence': evidence, 'data': data,
              'limitations': 'Quotes and hashes establish provenance, not semantic entailment or marketing quality. Agent reasoning requires behavioral evaluation.'}
    record['source_hashes'] = {name: sha(source_path(cfg.repo_root, name).read_bytes()) for name in data.get('source_files', [])}
    record['digest'] = sha(encoded(record))
    pubstate.save_json(folder(cfg) / f"{section}-{record['digest']}.json", record)
    pubstate.save_json(folder(cfg) / f'{section}.json', record)
    return record


def status(cfg):
    states = {}
    for section in SECTIONS:
        try:
            record = load_valid(cfg, section)
            states[section] = {'status': 'ready', 'digest': record['digest'], 'path': str(folder(cfg) / f'{section}.json')}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            states[section] = {'status': 'needs_work', 'reason': str(exc)}
    return {'sections': states, 'next_section': next((s for s in SECTIONS if states[s]['status'] != 'ready'), 'choose')}


def learning(cfg, jobs):
    """Expose actual history to the next strategy decision without inventing a winner."""
    return {'strategy': status(cfg), 'interventions': [
        {'id': j['brief']['id'], 'hypothesis': j['brief']['hypothesis'], 'status': j['status'],
         'simulation': j.get('simulation', False), 'outcome': j.get('outcome'),
         'decisions': j.get('decisions', []), 'review_due': j.get('review_due')}
        for j in jobs], 'instruction': 'Use actual outcomes to revise hypotheses and opportunity selection. Missing data is unknown, not failure; simulations are never traffic proof.'}
