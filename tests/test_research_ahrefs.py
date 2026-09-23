"""Ahrefs collector wire contracts; no live API calls or paid units."""
import importlib.util
import json
from pathlib import Path

import pytest

from scripts.lib import research
from scripts.lib.config import Config


@pytest.mark.parametrize('operation,path,key,select', [
    ('volume', 'keywords-explorer/overview', 'keywords', 'keyword,volume,difficulty,cpc'),
    ('competitors', 'site-explorer/organic-competitors', 'competitors', 'competitor_domain,keywords_common,share'),
    ('ranked-keywords', 'site-explorer/organic-keywords', 'keywords', 'keyword,best_position,volume,sum_traffic,best_position_url'),
])
def test_ahrefs_collector_request_and_receipt(tmp_path, fake_transport, operation, path, key, select):
    cfg = Config(tmp_path, {'AHREFS_API_KEY': 'fixture-secret'})
    url = 'https://api.ahrefs.com/v3/' + path
    fake_transport.route('GET', url, {'body': json.dumps({key: [], 'echo': 'fixture-secret'})})
    out = research.collect(cfg, 'ahrefs', operation, query='export checklist', target='competitor.test',
                           country='DE', language='de', limit=3, allow_paid=True)
    assert out['checked']  # Empty but valid rows are a completed bounded request.
    params = {'country': 'de', 'limit': 3, 'select': select}
    if operation == 'volume':
        params['keywords'] = 'export checklist'
        assert 'snapshot_date' not in out['result']
    else:
        params.update(target='competitor.test', date=out['result']['observed_on'])
        assert out['result']['snapshot_date'] == params['date']
    wire = fake_transport.calls[0][2]
    assert wire['params'] == params
    assert wire['headers']['Authorization'] == 'Bearer fixture-secret'
    assert out['result']['applied_locale'] == {'country': 'de'}
    assert out['result']['unsupported_locale'] == ['location_code', 'language', 'search_location']
    saved = Path(out['output']).read_text()
    assert 'fixture-secret' not in saved
    assert json.loads(saved)['source_url'] == url
    assert json.loads(saved)['cost_usd'] is None


def test_ahrefs_missing_key_and_invalid_requests_do_not_spend(tmp_path, fake_transport):
    cfg = Config(tmp_path, {'AHREFS_API_KEY': 'fixture-secret'})
    for args, message in [
        ({'allow_paid': False}, 'allow-paid'),
        ({'country': 'Germany'}, 'country'),
        ({'query': 'one,two', 'limit': 1}, 'comma-separated'),
        ({'query': 'one,'}, 'comma-separated'),
    ]:
        with pytest.raises(ValueError, match=message):
            research.collect(cfg, 'ahrefs', 'volume', **{'query': 'export', 'allow_paid': True, **args})
    missing = research.collect(Config(tmp_path), 'ahrefs', 'volume', query='export', allow_paid=True)
    assert not missing['checked'] and 'credentials missing' in missing['result']['error']
    assert Path(missing['output']).is_file()
    assert not list((cfg.state_dir / 'research').glob('calls-*.json'))
    assert not fake_transport.calls


@pytest.mark.parametrize('response', [
    {'status': 403, 'body': 'Denied fixture-secret'},
    {'body': '{"error":"quota", "keywords":[]}'},
    {'body': '{"keywords":null}'},
])
def test_ahrefs_failure_is_saved_and_consumes_daily_allowance(tmp_path, fake_transport, response):
    cfg = Config(tmp_path, {'AHREFS_API_KEY': 'fixture-secret'},
                 {'growth': {'research': {'daily_call_limit': 1}}})
    fake_transport.route('GET', 'https://api.ahrefs.com/v3/keywords-explorer/overview', response)
    out = research.collect(cfg, 'ahrefs', 'volume', query='export', allow_paid=True)
    assert not out['checked'] and out['result']['error']
    assert 'fixture-secret' not in Path(out['output']).read_text()
    with pytest.raises(ValueError, match='daily research'):
        research.collect(cfg, 'ahrefs', 'volume', query='export', allow_paid=True)
    assert len(fake_transport.calls) == 1


def test_ahrefs_cli_accepts_provider_and_preserves_keyword_difficulty(tmp_path, fake_transport, monkeypatch, capsys):
    root = Path(__file__).resolve().parents[1]
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, root / path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    cli = load('ahrefs_research_cli', '02-research/scripts/research_market.py')
    cfg = Config(tmp_path, {'AHREFS_API_KEY': 'fixture-secret'})
    monkeypatch.setattr(cli.config_module, 'load', lambda: cfg)
    monkeypatch.setattr('sys.argv', ['research_market.py', '--provider', 'ahrefs', '--operation', 'volume',
                                   '--query', 'export', '--country', 'US', '--allow-paid'])
    fake_transport.route('GET', 'https://api.ahrefs.com/v3/keywords-explorer/overview',
                         {'body': '{"keywords":[{"keyword":"export","volume":12,"difficulty":7,"cpc":20}]}'})
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)['result']['provider'] == 'ahrefs'
    opportunities = load('ahrefs_opportunities', '02-research/seo-keyword-research/scripts/find_opportunities.py')
    context, _ = opportunities._attach_ahrefs_context(cfg, ['export'])
    assert context['export']['keyword_difficulty'] == 7
