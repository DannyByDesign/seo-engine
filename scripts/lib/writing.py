"""Small, diverse human-reference packets and exact-overlap diagnostics."""
import hashlib
import random
import re
from pathlib import Path

CORPUS = Path(__file__).resolve().parents[2] / '05-execute/seo-copywriting/corpus'
MODES = {'landing': ('web-copy', 'web-editorial', 'commercial', 'instruction'),
         'article': ('reporting', 'analysis', 'web-editorial', 'science', 'essay', 'memoir', 'fiction'),
         'docs': ('web-copy', 'web-editorial', 'instruction', 'science'),
         'news': ('reporting', 'analysis', 'web-editorial'),
         'essay': ('essay', 'memoir', 'fiction', 'analysis', 'web-editorial', 'instruction', 'reporting', 'commercial')}


def examples():
    rows = []
    for block in re.split(r'^## ', (CORPUS / 'passages.md').read_text(), flags=re.M)[1:]:
        ident, rest = block.split('\n', 1)
        header, body = rest.strip().split('\n---\n\n', 1)
        fields = dict(line.split(': ', 1) for line in header.strip().splitlines())
        rows.append({'id': ident, 'source_id': fields['Source'], 'genre': fields['Genre'],
                     'tones': fields['Tone'].split(', '), 'text': body.strip(),
                     'modes': fields.get('Use', '').split(', ') if fields.get('Use') else [],
                     'technique': fields.get('Technique', ''), 'application_note': fields.get('Note', '')})
    return rows


def select(mode='article', seed='', limit=6):
    if mode not in MODES or not 3 <= limit <= 10: raise ValueError('choose a writing mode and 3..10 examples')
    rng = random.Random(str(seed))
    rows = [row for row in examples() if mode in row.get('modes', [])]; rng.shuffle(rows)
    selected, sources = [], set()
    for _ in range(limit):
        for genre in MODES[mode]:
            row = next((r for r in rows if r['genre'] == genre and r['source_id'] not in sources), None)
            if row:
                selected.append(row); sources.add(row['source_id'])
                if len(selected) == limit: return selected
    return selected


def packet(mode='article', seed='', limit=6):
    check = verify()
    if not check['checked']: raise ValueError('Frozen corpus verification failed: ' + '; '.join(check['errors'][:3]))
    rows = select(mode, seed, limit)
    return {'purpose': 'Learn multiple writing moves, never import source facts or mimic one author. Research evidence remains the authority for claims.',
            'mode': mode, 'examples': rows, 'example_ids': [r['id'] for r in rows],
            'selection_basis': 'Local Markdown passages with task eligibility, then genre/source diversity; seed varies selection, not semantic retrieval.'}


def render_packet(data):
    return data['purpose'] + '\n\n' + '\n\n'.join(
        f"Human reference {r['id']} ({r['genre']}; {', '.join(r['tones'])}):\n{r['text']}\nTechnique: {r['technique']}. {r['application_note']}" for r in data['examples'])


def prompt(mode='article', seed=''):
    return render_packet(packet(mode, seed))


def verify():
    texts, errors = {}, []
    for path in sorted((CORPUS / 'sources').glob('*.md')):
        header, body = path.read_text().split('\n---\n\n', 1)
        fields = dict(line.split(': ', 1) for line in header.strip().splitlines())
        if hashlib.sha256(body.encode()).hexdigest() != fields['SHA256']: errors.append('source hash: ' + path.stem)
        texts[path.stem] = ' '.join(body.split())
    if not texts: errors.append('no local source writing')
    rows = examples()
    for row in rows:
        if ' '.join(row['text'].split()) not in texts.get(row['source_id'], ''): errors.append('not verbatim: ' + row['id'])
        if row['modes'] and (not row['technique'] or not row['application_note'] or set(row['modes']) - set(MODES)):
            errors.append('invalid task metadata: ' + row['id'])
    return {'checked': not errors, 'sources': len(texts), 'examples': len(rows), 'errors': errors}


def overlap(text):
    tokens = re.findall(r"\b[\w']+\b", text.lower())
    windows = {' '.join(tokens[i:i+12]) for i in range(max(0,len(tokens)-11))}
    matches = []
    for row in examples():
        words = re.findall(r"\b[\w']+\b", row['text'].lower())
        phrase = next((' '.join(words[i:i+12]) for i in range(max(0,len(words)-11)) if ' '.join(words[i:i+12]) in windows), None)
        if phrase: matches.append({'example_id': row['id'], 'phrase': phrase})
    return {'matches': matches[:20], 'match_count': len(matches),
            'interpretation': 'Exact twelve-word overlap with excerpt bank; inspect and rewrite accidental copying. No matches is not proof of originality or human authorship.'}
