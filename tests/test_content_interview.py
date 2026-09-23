"""Per-topic interviews are required inputs, not blanket publication consent."""
import json
from pathlib import Path

import pytest

from scripts.lib import content, editorial, growth, publication, pubstate
from content_helpers import approved
import test_pub_write_enhance as writing_tests
import test_pub_publish_monitor as publishing_tests
from test_growth_workflow import brief


def test_proposed_use_is_private_filtered_scoped_and_digest_bound(tmp_path):
    ref = approved(tmp_path, 'page:/guide')
    record = pubstate.load_json(Path(ref['path']))
    data = {**record['data'], 'contribution': 'Changed proposed contribution', 'private_notes': 'SECRET-NOT-FOR-WRITER'}
    proposal = content.prepare(tmp_path, 'page:/guide', data)
    assert proposal['status'] == 'awaiting_confirmation'
    assert 'SECRET-NOT-FOR-WRITER' not in Path(ref['path']).read_text()
    with pytest.raises(ValueError, match='confirmation'):
        content.load(ref, 'page:/guide', tmp_path)
    with pytest.raises(ValueError, match='proposal changed'):
        content.confirm(tmp_path, 'page:/guide', ref['digest'], 'Operator', 'Yes')
    ref = content.confirm(tmp_path, 'page:/guide', proposal['digest'], 'Operator', 'Approved for this page only')
    assert content.prepare(tmp_path, 'page:/guide', data)['status'] == 'approved'
    assert content.load(ref, 'page:/guide', tmp_path)['contribution'] == data['contribution']
    with pytest.raises(ValueError, match='another article'):
        content.load(ref, 'page:/other', tmp_path)
    with pytest.raises(ValueError, match='target workspace'):
        content.load(ref, 'page:/guide', tmp_path / 'other-company')


def test_pipeline_stops_before_writing_on_successful_research_pause(tmp_path, monkeypatch, capsys):
    cfg, root = publishing_tests._repo(tmp_path)
    publication.write_post(root / 'drafts/new.md', {'slug': 'new', 'title': 'New topic'}, '')
    calls = []
    def run(cmd, repo):
        calls.append(cmd)
        return {'exit': 0, 'stderr': '', 'result': {'status': 'awaiting_interview', 'next_step': 'Ask operator'}}
    monkeypatch.setattr(publishing_tests.pipeline_mod, 'run_step', run)
    result = publishing_tests._run(publishing_tests.pipeline_mod, cfg, ['--publication', root.name, '--slug', 'new'], monkeypatch, capsys)
    assert result['status'] == 'awaiting_interview'
    assert len(calls) == 1 and calls[0][1].endswith('research_outline.py')
    assert 'awaiting_approval' not in result
    assert not pubstate.state_path(cfg, 'prepared', root.name + '-new').exists()


def test_direct_writer_refuses_missing_confirmation_without_model_call(tmp_path, monkeypatch, capsys):
    cfg, root = writing_tests._repo(tmp_path, ANTHROPIC_API_KEY='fixture')
    publication.write_post(root / 'drafts/new.md', {'slug': 'new', 'research': {'status': 'done', 'outline': {'sections': [{'heading': 'H'}]}}}, '')
    def forbidden(*a, **kw):
        pytest.fail('model called before operator approval')
    monkeypatch.setattr(writing_tests.write_mod.llm, 'complete_json', forbidden)
    result = writing_tests._run(writing_tests.write_mod, cfg, ['--publication', root.name, '--slug', 'new'], monkeypatch, capsys)
    assert result['_exit'] == 1 and 'interview' in result['error']


def test_firsthand_evidence_survives_writer_and_review_without_public_url(tmp_path, monkeypatch, capsys):
    cfg, root = writing_tests._repo(tmp_path, ANTHROPIC_API_KEY='fixture')
    public = tmp_path / 'source.txt'; public.write_text('Public guidance discusses reporting dashboards.')
    research = {'topic': 'Agency evaluation', 'plan': {'queries': ['agency evaluation']},
                'sources': [{'index': 1, 'url': 'https://fixture.test/guide', 'title': 'Guide', 'cache': str(public)}]}
    item = {'id': 'lesson', 'text': 'Our team tested 12 reports and found the missing context useful.',
            'kind': 'experience', 'attribution': 'Our operations team', 'limits': 'Only our own work; not an industry-wide finding.'}
    ref = approved(tmp_path, content.publication_id(root, 'guide'), research, [item])
    data = content.load(ref)
    research['sources'] += content.sources(data, 2)
    point = {'claim': item['text'], 'quote': item['text'], 'source': 2}
    outline = {'sections': [{'heading': 'What our team learned', 'goal': 'Explain the finding and scope', 'points': [point]}]}
    result = writing_tests.research_mod.verify(outline, research['sources'])
    assert result['kept'] == 1
    research.update(status='done', outline=outline, paper_trail=result['paper_trail'])
    meta = {'slug': 'guide', 'title': 'Agency evaluation', 'content_brief': ref, 'research': research}
    publication.write_post(root / 'drafts/guide.md', meta, '')
    prompts = []
    def model(cfg, system, prompt, **kwargs):
        prompts.append(system + prompt)
        return {'candidates': [item['text'] + ' This account concerns our own work only.']}
    monkeypatch.setattr(writing_tests.write_mod.llm, 'complete_json', model)
    # Neither private notes nor the operator's confirmation text are writer inputs.
    record = pubstate.load_json(Path(ref['path']))
    record['private_notes'] = 'SECRET-CLIENT-NAME'
    record['approval']['statement'] += ' PRIVATE-CONFIRMATION-CONTEXT'
    pubstate.save_json(Path(ref['path']), record)
    out = writing_tests._run(writing_tests.write_mod, cfg, ['--publication', root.name, '--slug', 'guide', '--candidates', '1'], monkeypatch, capsys)
    assert out['_exit'] == 0, out
    assert not any('vs target 0' in note for note in out['notes'])
    meta, body = publication.read_post(root / 'drafts/guide.md')
    assert len(meta['writing_example_ids']) == 6
    assert 'FROZEN HUMAN WRITING REFERENCES' in prompts[0]
    assert item['limits'] in prompts[0] and item['attribution'] in prompts[0]
    assert 'SECRET-CLIENT-NAME' not in '\n'.join(prompts) + json.dumps(meta) + body
    assert 'PRIVATE-CONFIRMATION-CONTEXT' not in '\n'.join(prompts)
    assert 'interview:' not in body and ']()' not in body
    assert writing_tests.enhance_mod.stage_sources(meta, body, 'publication.test') == []
    assert writing_tests.enhance_mod.stage_verify(cfg, body, research, check_links=False)['unverified'] == []
    review = {'reviewer': 'Fixture editor', 'reader_need': 'Readers need a specific example with its limits.',
              'value_added': 'A clearly attributed first-hand account with limited scope.',
              'facts_checked': True, 'disclosure_checked': True,
              'claims': [{'claim': item['text'], 'quote': item['text'], 'source': 'interview:lesson',
                          'assessment': 'An approved account of this team only; not a general industry result.'}]}
    meta['editorial_review'] = editorial.record_review(meta, body, root, review)
    assert editorial.valid_review(meta, body, root)
    pub = publication.load_publication(root)
    post = publication.Post(slug='guide', meta=meta, body_md=body)
    publication.process_body(pub, post, None)
    rendered = publication.render_post_page(pub, post, None, {}, 2026)
    assert 'SECRET-CLIENT-NAME' not in rendered and 'interview:' not in rendered
    assert ref['path'] not in rendered and 'PRIVATE-CONFIRMATION-CONTEXT' not in rendered
    changed = {**data, 'constraints': ['Do not share this example anymore.']}
    content.prepare(tmp_path, ref['content_id'], changed)
    assert not editorial.valid_review(meta, body, root)
    public.write_text('Changed external source')
    with pytest.raises(ValueError):
        content.check_article(meta, root, 'guide', tmp_path)


def test_first_party_permissions_required_and_changes_block_deployment(tmp_path):
    (tmp_path / 'index.html').write_text('Old')
    b = brief('https://fixture.test', tmp_path)
    ref = b['content_briefs']['/']
    missing = {**b, 'content_briefs': {}}
    with pytest.raises(ValueError, match='interview'):
        growth.create(tmp_path, missing)
    job = growth.create(tmp_path, b)
    (tmp_path / 'index.html').write_text('Tested deployment procedure')
    growth.validate(tmp_path, job)
    data = content.load(ref)
    content.prepare(tmp_path, ref['content_id'], {**data, 'constraints': ['Do not publish this proposed contribution.']})
    with pytest.raises(ValueError, match='confirmation'):
        growth.deploy(tmp_path, job, approved=True)


def test_cli_prepare_requires_explicit_digest_confirmation(tmp_path):
    import os
    import subprocess
    import sys
    record_ref = approved(tmp_path, 'page:/cli')
    data = content.load(record_ref)
    data['contribution'] = 'A revised proposed contribution for this CLI test.'
    source = tmp_path / 'proposal.json'
    source.write_text(json.dumps(data))
    script = Path(__file__).resolve().parents[1] / '02-research/pub-research/scripts/content_brief.py'
    env = {**os.environ, 'SEO_REPO_ROOT': str(tmp_path)}
    def run(*args):
        proc = subprocess.run([sys.executable, str(script), '--content-id', 'page:/cli', *args],
                              env=env, capture_output=True, text=True)
        return proc.returncode, json.loads(proc.stdout)
    code, result = run('--action', 'prepare', '--file', str(source))
    assert code == 0 and result['status'] == 'awaiting_confirmation'
    code, error = run('--action', 'confirm', '--confirm-digest', record_ref['digest'],
                      '--operator', 'Fixture operator', '--confirmation', 'Approved')
    assert code == 1 and 'changed' in error['error']
    code, done = run('--action', 'confirm', '--confirm-digest', result['digest'],
                     '--operator', 'Fixture operator', '--confirmation', 'Approved for the CLI fixture only')
    assert code == 0 and content.load(done['content_brief'])['contribution'] == data['contribution']


def test_first_party_cli_accepts_post_edit_review_and_rejects_review_only_change(tmp_path):
    import os
    import subprocess
    import sys
    (tmp_path / 'index.html').write_text('Old content')
    b = brief('https://fixture.test', tmp_path)
    reviews = b.pop('content_reviews')
    proposal = tmp_path / '.seo-engine' / 'growth-input.json'
    proposal.write_text(json.dumps(b))
    review_file = tmp_path / '.seo-engine' / 'content-review.json'
    review_file.write_text(json.dumps(reviews))
    script = Path(__file__).resolve().parents[1] / '04-choose/seo-growth/scripts/run_growth.py'
    def run(*args):
        return subprocess.run([sys.executable, str(script), *args],
                              env={**os.environ, 'SEO_REPO_ROOT': str(tmp_path)}, capture_output=True, text=True)
    assert run('--stage', 'create', '--brief-file', str(proposal)).returncode == 0
    missing = run('--stage', 'validate', '--id', b['id'])
    assert missing.returncode != 0 and 'content-review-file' in missing.stderr
    unchanged = run('--stage', 'validate', '--id', b['id'], '--content-review-file', str(review_file))
    assert unchanged.returncode == 1 and 'no declared source change' in unchanged.stdout
    (tmp_path / 'index.html').write_text('Tested deployment procedure')
    validated = run('--stage', 'validate', '--id', b['id'], '--content-review-file', str(review_file))
    assert validated.returncode == 0, validated.stdout + validated.stderr
    job = json.loads(validated.stdout)['job']
    assert job['status'] == 'validated' and job['brief']['content_reviews']['/']['disclosure_checked']
