import json
from pathlib import Path

from scripts.lib import languagetool as lt
from scripts.lib.config import Config


def response(matches=None):
    return {'language': {'code': 'en-US'}, 'software': {'name': 'LanguageTool', 'version': 'fixture'}, 'matches': matches or []}


def test_extraction_preserves_inline_punctuation_and_paragraph_boundaries():
    source = '# Export jobs\n\nRead [this guide](/guide).\n\nChoose **Export** when ready.'
    assert lt.prose(source) == 'Export jobs\n\nRead this guide.\n\nChoose Export when ready.'
    assert lt.prose('<p>Try <em>this</em>!</p><p>Next.</p>', 'html') == 'Try this!\n\nNext.'


def test_proofreading_wire_unicode_and_immutable_source(tmp_path, fake_transport):
    cfg = Config(tmp_path, {'LANGUAGETOOL_URL': lt.PAID_URL, 'LANGUAGETOOL_USERNAME': 'editor@test.invalid', 'LANGUAGETOOL_API_KEY': 'private-test-key'})
    original = '---\ntitle: Hidden typo\n---\n\n😀 This is an test.\n\n```python\ncode_typo = 1\n```'
    match = {'offset': 11, 'length': 2, 'message': 'Use a', 'replacements': [{'value': 'a'}], 'rule': {'id': 'EN_A_VS_AN'}, 'context': {'text': 'This is an test.'}}
    fake_transport.route('POST', lt.PAID_URL, {'body': json.dumps(response([match]))})
    result = lt.check(cfg, original, language='en-US', level='picky')
    assert result['checked'] and result['match_count'] == 1
    report = json.loads(Path(result['output']).read_text())
    assert report['matches'][0]['text'] == 'an'
    assert report['matches'][0]['offset'] == 10
    wire = fake_transport.calls[0][2]
    assert wire['data']['username'] == 'editor@test.invalid' and wire['data']['apiKey'] == 'private-test-key'
    assert wire['data']['language'] == 'en-US' and wire['data']['level'] == 'picky'
    assert wire['allow_redirects'] is False
    assert wire['data']['text'] == '😀 This is an test.'
    assert 'private-test-key' not in Path(result['output']).read_text()
    assert 'Hidden typo' in original  # checker returns suggestions, never rewritten source


def test_chunk_failure_retains_partial_coverage_without_retry(tmp_path, fake_transport):
    url = 'http://127.0.0.1:8081/v2/check'
    cfg = Config(tmp_path, {'LANGUAGETOOL_URL': url, 'LANGUAGETOOL_CHUNK_CHARS': '100', 'LANGUAGETOOL_API_KEY': 'not-for-local'})
    fake_transport.route('POST', url, {'body': json.dumps(response())}, {'status': 429, 'body': 'quota'})
    result = lt.check(cfg, 'A normal sentence. ' * 30, format='text')
    report = json.loads(Path(result['output']).read_text())
    assert not result['checked'] and result['completed_chunks'] == 1
    assert 0 < report['checked_characters'] < report['characters']
    assert len(fake_transport.calls) == 2
    assert 'apiKey' not in fake_transport.calls[0][2]['data']


def test_no_public_automation_or_silent_success(tmp_path, fake_transport):
    for env in ({}, {'LANGUAGETOOL_URL': 'https://api.languagetool.org/v2/check'}, {'LANGUAGETOOL_URL': lt.PAID_URL}):
        result = lt.check(Config(tmp_path, env), 'This is an test.')
        assert not result['checked'] and Path(result['output']).is_file()
    assert not fake_transport.calls


def test_html_extraction_auto_variant_and_incomplete_response(tmp_path, fake_transport):
    cfg = Config(tmp_path, {'LANGUAGETOOL_URL': 'http://localhost:8081/v2/check', 'LANGUAGETOOL_PREFERRED_VARIANTS': 'en-GB,de-DE'})
    raw = response(); raw['warnings'] = {'incompleteResults': True}
    fake_transport.route('POST', 'http://localhost:8081/v2/check', {'body': json.dumps(raw)})
    result = lt.check(cfg, '<p>Read <a href="https://example.test">this</a>.</p><div hidden>Ignore me</div><script>bad()</script>', format='html', language='auto')
    assert not result['checked']
    assert fake_transport.calls[0][2]['data']['preferredVariants'] == 'en-GB,de-DE'
    assert 'Ignore' not in fake_transport.calls[0][2]['data']['text']


def test_redirect_is_not_followed_or_reported_as_success(tmp_path, fake_transport):
    fake_transport.route('POST', lt.PAID_URL, {'status': 307, 'headers': {'Location': 'https://unrelated.invalid/check'}})
    cfg = Config(tmp_path, {'LANGUAGETOOL_URL': lt.PAID_URL, 'LANGUAGETOOL_USERNAME': 'fixture', 'LANGUAGETOOL_API_KEY': 'fixture-key'})
    result = lt.check(cfg, 'A draft.', format='text')
    assert not result['checked'] and 'redirects' in result['error']
    assert len(fake_transport.calls) == 1


def test_final_editing_stage_records_current_text_and_dry_run_skips(tmp_path, fake_transport, monkeypatch, capsys):
    import importlib.util
    import sys
    from scripts.lib import publication
    test_path = Path(__file__).with_name('test_pub_write_enhance.py')
    spec = importlib.util.spec_from_file_location('lt_pipeline_fixture', test_path)
    helpers = importlib.util.module_from_spec(spec); spec.loader.exec_module(helpers)
    cfg, root = helpers._repo(tmp_path)
    cfg.env['LANGUAGETOOL_URL'] = 'http://localhost:8081/v2/check'
    path = root / 'drafts/sample.md'
    publication.write_post(path, {'title': 'Sample'}, 'This is an test.')
    fake_transport.route('POST', cfg.env['LANGUAGETOOL_URL'], {'body': json.dumps(response())})
    result = helpers._run(helpers.enhance_mod, cfg, ['--publication', root.name, '--slug', 'sample', '--stages', 'language'], monkeypatch, capsys)
    assert result['languagetool']['checked']
    meta, body = publication.read_post(path)
    assert meta['languagetool']['source_sha256'] == lt.hashlib.sha256(body.encode()).hexdigest()
    before = path.read_bytes()
    result = helpers._run(helpers.enhance_mod, cfg, ['--publication', root.name, '--slug', 'sample', '--stages', 'language', '--dry-run'], monkeypatch, capsys)
    assert result['languagetool']['status'] == 'dry_run'
    assert len(fake_transport.calls) == 1 and path.read_bytes() == before
