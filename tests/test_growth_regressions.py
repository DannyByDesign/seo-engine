"""Counterexamples from the product evaluation; no network or paid models."""
import hashlib
import importlib.util
from pathlib import Path

from scripts.lib import publication, pubstate

ROOT = Path(__file__).resolve().parents[1]

def load(path):
    spec = importlib.util.spec_from_file_location(Path(path).stem + '_regression', ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

t = load('tests/test_pub_publish_monitor.py')
research = load('skills/pub-research/scripts/research_outline.py')


def test_refetch_changed_source_preserves_published_review(tmp_path, monkeypatch):
    from scripts.lib import editorial
    cfg, root = t._repo(tmp_path)
    t._ready_draft(root, 'ready', 'sp-0001')
    meta, body = publication.read_post(root / 'drafts/ready.md')
    original = editorial.plain(body)
    monkeypatch.setattr(research, 'fetch_text', lambda *_: ('Source', original))
    candidates = [{'url': 'https://e.com/a', 'origin': 'seed'}]
    cache = cfg.state_dir / 'pub-research' / root.name / 'ready'
    sources = research.read(cfg, candidates, 1, cache)
    meta['research']['sources'] = sources
    meta['editorial_review'] = editorial.record_review(meta, body, root, meta['editorial_review'])
    meta.update(status='published', published_at='2026-01-01T00:00:00Z')
    publication.write_post(root / 'posts/ready.md', meta, body)
    assert editorial.valid_review(meta, body, root)
    monkeypatch.setattr(research, 'fetch_text', lambda *_: ('Source', original + ' Updated source evidence.'))
    refreshed = research.read(cfg, candidates, 1, cache)
    assert refreshed[0]['cache'] != sources[0]['cache']
    assert Path(sources[0]['cache']).read_text() == original
    assert Path(refreshed[0]['cache']).read_text().endswith('Updated source evidence.')
    assert editorial.valid_review(meta, body, root)
    builder = load('skills/pub-site/scripts/build_site.py')
    assert builder.build_one(root, None, False)['validation']['errors'] == 0


def test_installer_ignores_secrets_and_state_in_real_worktree(tmp_path):
    import subprocess
    checkout = tmp_path / 'checkout'; checkout.mkdir()
    def git(*args):
        return subprocess.run(['git', '-C', str(checkout), *args], check=True, capture_output=True, text=True)
    git('init')
    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test', 'commit', '--allow-empty', '-m', 'Fixture')
    worktree = tmp_path / 'worktree'
    git('worktree', 'add', '--detach', str(worktree), 'HEAD')
    assert (worktree / '.git').is_file()
    subprocess.run(['bash', str(ROOT / 'install.sh'), str(ROOT), str(worktree), 'codex'], check=True, capture_output=True)
    assert (worktree / '.env').is_file()
    ignored = subprocess.run(['git', '-C', str(worktree), 'check-ignore', '.env', '.seo-engine/state/test.json'],
                             check=True, capture_output=True, text=True)
    assert ignored.stdout.splitlines() == ['.env', '.seo-engine/state/test.json']


def test_reject_partial_fabricated_quote_and_remove_opening(tmp_path):
    text = 'The survey found that 42% of respondents abandoned checkout.'
    assert research.verify_quote(text, text)
    assert not research.verify_quote(text + ' This guarantees 900% returns.', text)
    p = tmp_path / 'source'; p.write_text(text)
    outline = {'opening': {'claim': '999% returns', 'quote': 'invented', 'source': 1}, 'sections': []}
    result = research.verify(outline, [{'index': 1, 'url': 'https://example.org', 'title': 'Survey', 'cache': str(p)}])
    assert result['dropped'] == 1 and 'opening' not in outline


def test_gate_rejects_filler_duplicate_sources_and_unverified():
    meta = {'research': {'status': 'done'}, 'enhanced_at': 'now', 'cover': {'src': 'cover.svg'},
            'sources': [{'url': 'https://example.org'}] * 3, 'verification': {'unverified': ['999%']}}
    problems = t.publish_mod.gate(meta, 'filler ' * 1200, {}, min_words=1, min_sources=0)
    assert 'repetitive content' in problems and 'unverified numbers remain' in problems
    assert any('sources' in p for p in problems)
    assert any('words' in p for p in t.publish_mod.gate(meta, 'short body', {}, min_words=0, min_sources=0))


def test_approval_resumes_prepared_body_unchanged(tmp_path, monkeypatch, capsys):
    cfg, root = t._repo(tmp_path)
    t._ready_draft(root, 'ready', 'sp-0001')
    path = root / 'drafts/ready.md'
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    pubstate.save_json(pubstate.state_path(cfg, 'prepared', root.name + '-ready'), {'sha256': digest})
    out = t._run(t.pipeline_mod, cfg, ['--publication', root.name, '--slug', 'ready', '--approve', '--dry-run'], monkeypatch, capsys)
    assert [p['step'] for p in out['plan']] == ['publish', 'relink', 'build']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    path.write_text(path.read_text() + '\nChanged after preparation.\n')
    refused = t._run(t.pipeline_mod, cfg, ['--publication', root.name, '--slug', 'ready', '--approve'], monkeypatch, capsys)
    assert refused['_exit'] == 1 and 'changed' in refused['error']


def test_elapsed_review_window_and_published_resume(tmp_path, monkeypatch, capsys):
    cfg, root = t._repo(tmp_path)
    t._ready_draft(root, 'ready', 'sp-0001')
    site = pubstate.load_yaml(root / 'site.yml'); site['planner'] = {'approval_mode': 'review_window', 'review_window_hours': 1}
    pubstate.save_yaml(root / 'site.yml', site)
    t._review_draft(root, 'ready', '2026-01-01T00:00:00Z')
    out = t._run(t.pipeline_mod, cfg, ['--publication', root.name, '--slug', 'ready', '--dry-run'], monkeypatch, capsys)
    assert 'publish' in [p['step'] for p in out['plan']]
    (root / 'drafts/ready.md').rename(root / 'posts/ready.md')
    out = t._run(t.pipeline_mod, cfg, ['--publication', root.name, '--slug', 'ready', '--dry-run'], monkeypatch, capsys)
    # A recovery build does not require renewed approval of already-published content.
    assert [p['step'] for p in out['plan']] == ['relink', 'build']


def test_refresh_keeps_url_and_original_date(tmp_path, monkeypatch, capsys):
    cfg, root = t._repo(tmp_path)
    publication.write_post(root / 'posts/old.md', {'title': 'Original title', 'published_at': '2020-01-01T00:00:00Z', 'author': 'ezra-mbeki'}, 'Original body')
    tm = {'pillars': [{'slug': 'ai-search', 'spokes': [{'id': 'refresh', 'status': 'open', 'subtopic': 'Refresh: Original title', 'refresh_of': 'old'}]}]}
    state = {'slots': [{'id': 'due', 'status': 'planned', 'scheduled_for': '2026-01-01T00:00:00Z'}]}
    t.planner_mod.queue_slots(root, publication.load_publication(root), state, tm, {'items': []}, 'topic_map')
    meta, body = publication.read_post(root / 'drafts/old.md')
    assert meta['refresh_of'] == 'old' and meta['original_published_at'] == '2020-01-01T00:00:00Z'
    assert meta['title'] == 'Original title' and not body
    assert (root / 'posts/old.md').read_text().endswith('Original body')


def test_no_history_is_not_indexing_failure(tmp_path):
    from datetime import datetime, timezone
    post = publication.Post(slug='old', meta={'published_at': '2020-01-01T00:00:00Z'}, body_md='Evergreen')
    findings = t.refresh_mod.triggers_for(post, [], {}, now=datetime.now(timezone.utc), drop_ratio=.5, min_prior_clicks=10, max_age_days=180, awaiting_days=45)
    assert not any(f['trigger'] in ('never_indexed', 'no_recorded_impressions') for f in findings)


def test_editorial_receipt_binds_content_evidence_assets_and_policy(tmp_path):
    from scripts.lib import editorial
    cfg, root = t._repo(tmp_path)
    t._ready_draft(root, 'ready', 'sp-0001')
    meta, body = publication.read_post(root / 'drafts/ready.md')
    assert editorial.valid_review(meta, body, root)
    assert not editorial.valid_review(meta, body + ' Unsupported addition.', root)
    assert not editorial.valid_review({**meta, 'title': 'Changed meaning'}, body, root)
    source = Path(meta['research']['sources'][0]['cache'])
    old = source.read_text(); source.write_text('Changed evidence')
    assert not editorial.valid_review(meta, body, root)
    source.write_text(old)
    asset = root / 'assets/ready/cover.svg'; old = asset.read_text(); asset.write_text('Changed image')
    assert not editorial.valid_review(meta, body, root)
    asset.write_text(old)
    (root / 'site.yml').write_text((root / 'site.yml').read_text() + '\n# changed policy\n')
    assert not editorial.valid_review(meta, body, root)


def test_skip_checks_cannot_bypass_editorial_review(tmp_path, monkeypatch, capsys):
    cfg, root = t._repo(tmp_path)
    t._ready_draft(root, 'ready', 'sp-0001')
    path = root / 'drafts/ready.md'; meta, body = publication.read_post(path)
    meta.pop('editorial_review'); publication.write_post(path, meta, body)
    out = t._run(t.publish_mod, cfg, ['--publication', root.name, '--slug', 'ready', '--approve', '--skip-checks'], monkeypatch, capsys)
    assert out['_exit'] == 1 and not out['published']
    assert path.is_file() and not (root / 'posts/ready.md').exists()


def test_published_receipt_remains_valid_and_relink_only_proposes(tmp_path, monkeypatch, capsys):
    from scripts.lib import editorial
    cfg, root = t._repo(tmp_path)
    t._ready_draft(root, 'ready', 'sp-0001')
    out = t._run(t.publish_mod, cfg, ['--publication', root.name, '--slug', 'ready', '--approve', '--relink', '--build'], monkeypatch, capsys)
    assert out['_exit'] == 0
    meta, body = publication.read_post(root / 'posts/ready.md')
    assert editorial.valid_review(meta, body, root)


def test_build_rejects_removed_review_without_destroying_existing_output(tmp_path):
    cfg, root = t._repo(tmp_path)
    t._ready_draft(root, 'ready', 'sp-0001')
    draft = root / 'drafts/ready.md'; meta, body = publication.read_post(draft)
    meta.pop('editorial_review'); meta['status'] = 'published'; meta['published_at'] = '2026-01-01T00:00:00Z'; publication.write_post(root / 'posts/ready.md', meta, body)
    dist = root / 'dist'; dist.mkdir(); (dist / 'keep.txt').write_text('last good build')
    builder = load('skills/pub-site/scripts/build_site.py')
    result = builder.build_one(root, None, False)
    assert result['validation']['errors'] == 1
    assert (dist / 'keep.txt').read_text() == 'last good build'


def test_small_probe_samples_never_drive_content_gap():
    row = {'prompt': 'Which vendor?', 'mentions': {'comp': {'mentioned': True, 'count': 1}}, 'citations': []}
    result = t.mentions_mod.summarize([row], {'brand':'Us','comp':'Them'})
    assert result['measurement_verdict'] == 'thin-sample'
    assert not t.mentions_mod.per_prompt([row], {'brand':'Us','comp':'Them'})[0]['competitor_wins']
    assert t.mentions_mod.per_prompt([row]*10, {'brand':'Us','comp':'Them'})[0]['competitor_wins']


def test_render_failure_preserves_last_good_build(tmp_path, monkeypatch):
    cfg, root = t._repo(tmp_path); t._ready_draft(root, 'ready', 'sp-0001')
    path = root / 'drafts/ready.md'; meta, body = publication.read_post(path)
    meta['published_at'] = '2026-01-01T00:00:00Z'; publication.write_post(root / 'posts/ready.md', meta, body)
    dist = root/'dist'; dist.mkdir(); (dist/'index.html').write_text('last good')
    builder = load('skills/pub-site/scripts/build_site.py')
    def broken(pub, out):
        out.mkdir(parents=True); (out/'index.html').write_text('half built')
        raise RuntimeError('simulated renderer failure')
    monkeypatch.setattr(builder.publication, 'build_site', broken)
    result = builder.build_one(root, None, False)
    assert result['validation']['errors'] and result['last_good_preserved']
    assert (dist/'index.html').read_text() == 'last good'


def test_atomic_refresh_write_failure_preserves_article(tmp_path, monkeypatch):
    path = tmp_path/'post.md'; path.write_text('last good article')
    def fail(*args): raise OSError('simulated interrupted rename')
    monkeypatch.setattr(pubstate.os, 'replace', fail)
    import pytest
    with pytest.raises(OSError): publication.write_post(path, {'title':'New'}, 'new body')
    assert path.read_text() == 'last good article'


def test_refresh_visuals_preserve_live_receipt_then_publish_new_bundle(tmp_path, monkeypatch, capsys):
    from scripts.lib import editorial
    cfg, root = t._repo(tmp_path); t._ready_draft(root, 'ready', 'sp-0001')
    initial = t._run(t.publish_mod, cfg, ['--publication', root.name, '--slug', 'ready', '--approve'], monkeypatch, capsys)
    assert initial['_exit'] == 0
    live_path = root / 'posts/ready.md'
    live_meta, live_body = publication.read_post(live_path)
    original_asset = (root / 'assets/ready/cover.svg').read_bytes()
    draft_meta = dict(live_meta); draft_meta['refresh_of'] = 'ready'
    publication.write_post(root / 'drafts/ready.md', draft_meta, live_body)
    cover = load('skills/pub-visuals/scripts/gen_cover.py')
    out = t._run(cover, cfg, ['--publication', root.name, '--slug', 'ready', '--provider', 'svg', '--force'], monkeypatch, capsys)
    assert out['_exit'] == 0
    meta, body = publication.read_post(root / 'drafts/ready.md')
    bundle = meta['asset_slug']; assert bundle != 'ready'
    enhancer = load('skills/pub-enhance/scripts/enhance_article.py')
    enhancer.stage_diagrams(root, bundle, body, {'outline': {'diagrams': [{'title': 'Review process', 'kind': 'flow', 'steps': ['Draft', 'Review']}]}})
    assert (root / 'assets' / bundle / 'diagram-1.json').is_file()
    assert (root / 'assets/ready/cover.svg').read_bytes() == original_asset
    assert editorial.valid_review(live_meta, live_body, root)
    builder = load('skills/pub-site/scripts/build_site.py')
    assert builder.build_one(root, None, False)['validation']['errors'] == 0
    import pytest
    with pytest.raises(ValueError, match='published assets'):
        enhancer.stage_diagrams(root, 'ready', body, {'outline': {'diagrams': [{'title': 'Forbidden'}]}})
    t._review_draft(root, 'ready')
    out = t._run(t.publish_mod, cfg, ['--publication', root.name, '--slug', 'ready', '--approve', '--build'], monkeypatch, capsys)
    assert out['_exit'] == 0, out
    meta, body = publication.read_post(live_path)
    assert meta['asset_slug'] == bundle and editorial.valid_review(meta, body, root)
    assert (root / 'dist/assets' / bundle / 'cover.svg').is_file()


def test_late_launch_burst_crossing_midnight_is_idempotent():
    from datetime import datetime,timezone,timedelta
    state={'slots':[]}; conf={**t.planner_mod.DEFAULT_PLANNER,'cadence_per_week':7,'publish_hour_utc':20,'launch_burst':4}
    now=datetime(2026,9,9,23,55,tzinfo=timezone.utc)
    created=t.planner_mod.materialize(state,conf,'test',days=3,published_count=0,now=now)
    assert len(created)==6
    assert t.planner_mod.materialize(state,conf,'test',days=3,published_count=0,now=now+timedelta(seconds=2))==[]
    assert state['slots'][0]['cadence_day']=='2026-09-09'
