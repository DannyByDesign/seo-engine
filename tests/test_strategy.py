"""Agent memory and real API wire contracts, using explicitly synthetic evidence."""
import json
from datetime import date
from pathlib import Path
import pytest
from scripts.lib import strategy, research
from scripts.lib.config import Config


def profile(root):
    (root / 'product.json').write_text('{"feature":"CSV export"}')
    return {'author': 'Fixture Agent', 'business': 'Export tool', 'conversion_goal': 'Start an export',
            'audiences': ['Operations teams'], 'source_files': ['product.json'], 'seed_queries': ['export workflow'],
            'commands': {'test': ['python3', '-m', 'unittest'], 'build': ['python3', 'build.py']}, 'unknowns': [],
            'evidence': [{'id': 'product', 'path': 'product.json', 'kind': 'repo', 'quote': 'CSV export', 'observed_on': date.today().isoformat()}],
            'claims': [{'text': 'CSV export exists.', 'kind': 'fact', 'evidence_ids': ['product']}]}


def market(root):
    (root / 'customer.txt').write_text('How do I export a checklist?')
    candidates = [{'id': name, 'query': 'export checklist', 'audience': 'operations', 'intent': 'solve export task',
                   'page': '/' + name, 'action': 'build useful guide', 'original_value': 'Tested examples of the actual product export workflow.',
                   'business_reason': 'The reader needs the exact workflow this product supplies.', 'business_value': 2, 'effort_hours': 1,
                   'evidence': [{'kind': 'customer_question', 'reference': 'support', 'snapshot': 'customer.txt',
                                 'observation': 'User asks about export', 'observed_on': date.today().isoformat()}]}
                  for name in ('guide', 'example')]
    return {'author': 'Fixture Agent', 'market_summary': 'Support asks about export', 'questions': ['How does export work?'],
            'competitors': [{'observation': 'Support evidence only; competitor coverage unknown'}], 'opportunities': candidates,
            'unknowns': ['Search volume is unknown'], 'evidence': [{'id': 'demand', 'kind': 'customer', 'path': 'customer.txt',
                       'quote': 'How do I export a checklist?', 'observed_on': date.today().isoformat()}],
            'claims': [{'text': 'A customer asks how to export.', 'kind': 'fact', 'evidence_ids': ['demand']}]}


def positioning():
    claims = [{'text': 'CSV export exists.', 'kind': 'fact', 'evidence_ids': ['product']}]
    return {'author': 'Fixture Agent', 'audience': 'Operations', 'problem': 'Exporting checklists', 'promise': 'Explain export steps',
            'differentiation': 'Working product examples', 'message_rules': ['Be concrete'], 'unknowns': [], 'claims': claims,
            'copy_briefs': [{'page': '/guide', 'reader_job': 'Export a checklist', 'angle': 'Tested walkthrough', 'cta': 'Try export', 'claims': claims}]}


def test_strategy_research_handoff_and_stale_evidence(tmp_path):
    cfg = Config(tmp_path)
    assert strategy.status(cfg)['next_section'] == 'understand'
    strategy.save(cfg, 'understand', profile(tmp_path))
    strategy.save(cfg, 'research', market(tmp_path))
    record = strategy.save(cfg, 'position', positioning())
    assert strategy.status(cfg)['next_section'] == 'choose'
    assert strategy.load_valid(cfg, 'position')['digest'] == record['digest']
    (tmp_path / 'product.json').write_text('Feature removed')
    assert strategy.status(cfg)['next_section'] == 'understand'
    with pytest.raises(ValueError, match='changed evidence'): strategy.load_valid(cfg, 'position')


def test_strategy_rejects_unsupported_claim_and_secret_snapshot(tmp_path):
    cfg = Config(tmp_path); data = profile(tmp_path)
    data['claims'][0]['evidence_ids'] = []
    with pytest.raises(ValueError, match='facts require'): strategy.save(cfg, 'understand', data)
    data = profile(tmp_path); (tmp_path / '.env').write_text('CSV export')
    data['evidence'][0]['path'] = '.env'
    with pytest.raises(ValueError, match='secret'): strategy.save(cfg, 'understand', data)


def test_inventory_avoids_engine_build_dependencies_and_secret_contents(tmp_path):
    (tmp_path / 'app.py').write_text('business code')
    for name in ('node_modules', 'dist', '.seo-engine', 'seo-engine/scripts/lib'):
        path = tmp_path / name; path.mkdir(parents=True); (path / 'strategy.py').write_text('engine')
    (tmp_path / '.env').write_text('NEVER_READ_SECRET')
    result = strategy.inspect_repo(Config(tmp_path))
    assert result['files'] == ['app.py']
    assert 'NEVER_READ_SECRET' not in json.dumps(result)


def test_research_paid_request_shape_saved_failure_and_durable_limit(tmp_path, fake_transport):
    cfg = Config(tmp_path, {'DATAFORSEO_LOGIN': 'fixture', 'DATAFORSEO_PASSWORD': 'secret-fixture'},
                 {'growth': {'research': {'daily_call_limit': 2}}})
    endpoint = 'https://api.dataforseo.com/v3/dataforseo_labs/google/keyword_ideas/live'
    raw = {'status_code': 20000, 'cost': 0.01, 'tasks': [{'status_code': 20000, 'result': [{'items': [{'keyword': 'export checklist'}]}]}]}
    fake_transport.route('POST', endpoint, {'body': json.dumps(raw)}, {'body': json.dumps({'status_code': 40501, 'status_message': 'Quota exceeded'})})
    with pytest.raises(ValueError, match='allow-paid'): research.collect(cfg, 'dataforseo', 'ideas', query='export')
    assert not fake_transport.calls
    out = research.collect(cfg, 'dataforseo', 'ideas', query='export', location=2276, language='de', limit=3, allow_paid=True)
    assert out['checked'] and Path(out['output']).is_file()
    wire = fake_transport.calls[0][2]
    assert wire['json'] == [{'keywords': ['export'], 'location_code': 2276, 'language_code': 'de', 'limit': 3, 'include_serp_info': True}]
    assert wire['auth'] == ('fixture', 'secret-fixture')
    failure = research.collect(cfg, 'dataforseo', 'ideas', query='export', allow_paid=True)
    assert not failure['checked'] and '40501' in failure['result']['error']
    assert Path(failure['output']).is_file()
    with pytest.raises(ValueError, match='daily research'): research.collect(cfg, 'dataforseo', 'ideas', query='export', allow_paid=True)
    assert len(fake_transport.calls) == 2


def test_brave_key_in_header_and_empty_search_is_not_google_volume(tmp_path, fake_transport):
    cfg = Config(tmp_path, {'BRAVE_SEARCH_API_KEY': 'fixture-secret'})
    fake_transport.route('GET', 'https://api.search.brave.com/res/v1/web/search',
                         {'body': json.dumps({'query': {'original': 'export'}, 'web': {'results': []}, 'echo': 'fixture-secret'})})
    result = research.collect(cfg, 'brave', 'search', query='export', country='DE', language='de', allow_paid=True)
    assert result['checked'] and 'not Google' in result['result']['scope']
    wire = fake_transport.calls[0][2]
    assert wire['headers']['X-Subscription-Token'] == 'fixture-secret'
    assert wire['params']['country'] == 'DE'
    assert 'fixture-secret' not in Path(result['output']).read_text()


def test_firecrawl_anonymous_response_and_application_failure(tmp_path, fake_transport):
    cfg = Config(tmp_path)
    fake_transport.route('POST', 'https://api.firecrawl.dev/v2/search',
        {'body': json.dumps({'success': True, 'data': {'web': [{'url': 'https://source.test', 'title': 'Source'}]}})},
        {'body': json.dumps({'success': False, 'error': 'quota'})})
    result = research.collect(cfg, 'firecrawl', 'search', query='public query', allow_paid=True)
    assert result['checked'] and result['result']['anonymous']
    assert 'Authorization' not in fake_transport.calls[0][2]['headers']
    assert result['result']['response']['data']['web'][0]['url'] == 'https://source.test'
    result = research.collect(cfg, 'firecrawl', 'search', query='public query', allow_paid=True)
    assert not result['checked'] and Path(result['output']).is_file()


def test_uncited_build_dependency_invalidates_strategy(tmp_path):
    cfg = Config(tmp_path); data = profile(tmp_path)
    (tmp_path / 'build.py').write_text('print("build")')
    data['source_files'].append('build.py')
    strategy.save(cfg, 'understand', data)
    strategy.save(cfg, 'research', market(tmp_path))
    strategy.save(cfg, 'position', positioning())
    (tmp_path / 'build.py').write_text('raise RuntimeError("new build contract")')
    assert strategy.status(cfg)['next_section'] == 'understand'


def test_large_research_response_is_saved_but_cli_preview_is_bounded(tmp_path, fake_transport):
    fake_transport.route('POST', 'https://api.firecrawl.dev/v2/search',
        {'body': json.dumps({'success': True, 'data': {'web': [{'description': 'detail ' * 100000}]}})})
    receipt = research.collect(Config(tmp_path), 'firecrawl', 'search', query='Wärmepumpe', country='DE',
                               language='de', location=2276, search_location='Berlin,Germany', allow_paid=True)
    summary = research.summary(receipt)
    assert len(json.dumps(summary)) < 6500 and summary['result']['preview_truncated']
    assert Path(receipt['output']).stat().st_size > 600000
    payload = fake_transport.calls[0][2]['json']
    assert payload['country'] == 'DE' and payload['location'] == 'Berlin,Germany'
    assert summary['result']['applied_locale'] == {'country': 'DE', 'location': 'Berlin,Germany'}
    assert 'language' in summary['result']['unsupported_locale']


def test_missing_credentials_and_missing_agent_leave_failures(tmp_path, monkeypatch, capsys):
    import importlib.util
    import sys
    cfg = Config(tmp_path)
    receipt = research.collect(cfg, 'brave', 'search', query='export', allow_paid=True)
    assert not receipt['checked'] and 'credentials missing' in receipt['result']['error']
    assert Path(receipt['output']).exists()
    assert not list((cfg.state_dir / 'research').glob('calls-*.json'))
    script = Path(__file__).resolve().parents[1] / '06-learn/scripts/run_cycle.py'
    spec = importlib.util.spec_from_file_location('blocked_cycle_test', script)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.config_module, 'load', lambda: cfg)
    monkeypatch.setattr(sys, 'argv', ['run_cycle.py', '--execute-agent'])
    assert mod.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert not result['checked'] and not result['agent_ran']
    assert json.loads((cfg.reports_dir / 'growth-cycle-last.json').read_text()) == result


def test_research_redacts_secrets_with_json_escape_characters(tmp_path, fake_transport):
    secret = 'secret"with\\escapes'
    fake_transport.route('GET', 'https://api.search.brave.com/res/v1/web/search',
                         {'body': json.dumps({'query': {'original': 'export'}, 'web': {'results': []}, 'echo': secret})})
    receipt = research.collect(Config(tmp_path, {'BRAVE_SEARCH_API_KEY': secret}), 'brave', 'search', query='export', allow_paid=True)
    assert receipt['checked'] and receipt['result']['response']['echo'] == 'REDACTED'
    assert json.loads(Path(receipt['output']).read_text())['response']['echo'] == 'REDACTED'
