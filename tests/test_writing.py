from scripts.lib import writing


def test_frozen_provenance_and_diverse_task_packets():
    report = writing.verify()
    assert report['checked'], report
    assert report['sources'] >= 30 and report['examples'] >= 300
    for mode in writing.MODES:
        rows = writing.select(mode, 'actual-page-topic')
        assert len(rows) == 6
        assert len({r['source_id'] for r in rows}) == 6
        assert len({r['genre'] for r in rows}) >= 2
        assert rows == writing.select(mode, 'actual-page-topic')
        assert rows != writing.select(mode, 'another-page-topic')
    row = writing.examples()[0]
    assert writing.overlap('New opening. ' + row['text'])['match_count'] >= 1
    assert not writing.overlap('Specific new product facts in a short sentence.')['matches']


def test_curated_packets_exclude_bad_task_examples():
    for seed in ('HVAC-dispatch-pricing', 'HVAC job CSV export', 'membership pricing'):
        landing = writing.packet('landing', seed)['examples']
        assert all('landing' in row['modes'] and row['technique'] for row in landing)
        assert not any(row['source_id'].startswith('pg-') for row in landing)
        assert not any('contributing' in row['text'].lower() or 'pull request' in row['text'].lower() for row in landing)
        news = writing.packet('news', seed)['examples']
        assert len({row['source_id'].split('-')[0] for row in news}) >= 3
        assert not any(row['source_id'].startswith('pg-') for row in news)


def test_copied_skill_resolves_explicit_engine_root(tmp_path):
    import os
    import shutil
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    copied = tmp_path / '.agents/skills/seo-copywriting/scripts'; copied.mkdir(parents=True)
    script = copied / 'writing_examples.py'
    shutil.copyfile(root / 'skills/seo-copywriting/scripts/writing_examples.py', script)
    result = subprocess.run([sys.executable, str(script), '--mode', 'landing', '--seed', 'copy-test'],
                            cwd=tmp_path, env={**os.environ, 'SEO_ENGINE_ROOT': str(root)}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'Product explanation' in result.stdout


def test_modified_frozen_source_blocks_automatic_packet(tmp_path, monkeypatch):
    import hashlib
    import pytest
    (tmp_path / 'sources').mkdir()
    source = tmp_path / 'sources/source.md'
    source.write_text('SHA256: ' + hashlib.sha256(b'Frozen human passage.').hexdigest() + '\n\n---\n\nFrozen human passage.')
    (tmp_path / 'passages.md').write_text('# Writing\n')
    monkeypatch.setattr(writing, 'CORPUS', tmp_path)
    source.write_text(source.read_text().replace('Frozen human passage.', 'Unexpected replacement.'))
    with pytest.raises(ValueError, match='source hash'): writing.packet()


def test_corpus_is_local_writing_not_link_or_json_catalog():
    from pathlib import Path
    import re
    assert not list(writing.CORPUS.rglob('*.json'))
    assert len(list((writing.CORPUS / 'sources').glob('*.md'))) == 38
    for path in (writing.CORPUS / 'sources').glob('*.md'):
        assert not re.search(r'https?://', path.read_text())
    assert 'original_value' not in (writing.CORPUS / 'passages.md').read_text()
