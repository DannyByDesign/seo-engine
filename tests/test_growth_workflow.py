"""First-party source -> actual local deploy -> HTTP verification; no public traffic claims."""
import functools
import http.server
import json
import sys
import threading
from pathlib import Path
import pytest
from scripts.lib import growth


def brief(url, root):
    from datetime import date
    from content_helpers import approved
    refs = {page: approved(root, 'page:' + page) for page in ('/', '/products/widget')}
    candidates = [{'id': key, 'query': 'deployment question', 'audience': 'developers', 'intent': 'learn setup',
        'page': '/', 'original_value': 'A reproducible tested example for this fixture only.',
        'business_reason': 'Exercise first-party workflow behavior; not actual demand.',
        'action': 'improve existing page', 'business_value': 2, 'effort_hours': hours,
        'evidence': [{'kind': 'customer_question', 'reference': 'https://fixture.test/question',
                      'observation': 'Synthetic fixture demand observation only.', 'observed_on': date.today().isoformat()}]}
        for key,hours in [('guide',1),('tool',2)]]
    return {'content_briefs': refs, 'content_reviews': {page: {'disclosure_checked': True, 'value_added': 'Synthetic fixture reviewed for workflow testing.'} for page in refs}, 'simulation': True, 'selection': {'candidates': candidates, 'selected_id': 'guide',
                         'rationale': 'This fixture prioritizes a small useful example over a larger tool.'},'id': 'useful-guide', 'site_url': url, 'hypothesis': 'Answering the deployment question can attract relevant organic visits.',
            'reader_need': 'Developers need a tested deployment procedure for the product.',
            'original_value': 'A reproducible example tested against the actual product code.',
            'demand_evidence': 'Synthetic test fixture; not measured query demand or traffic.',
            'rollback': 'Restore the previous content and redeploy the tested revision.',
            'source_files': ['index.html'], 'pages': [{'path': '/', 'expected_text': 'Tested deployment procedure', 'baseline_file':'index.html'}],
            'commands': {'test': [sys.executable, '-c', "from pathlib import Path; assert 'Tested deployment procedure' in Path('index.html').read_text()"],
                         'build': [sys.executable, '-c', "from pathlib import Path; assert Path('index.html').is_file()"],
                         'deploy': [sys.executable, '-c', "import shutil; shutil.copy('index.html','public/index.html')"]}}


def test_real_local_deploy_and_stale_validation_rejected(tmp_path):
    public = tmp_path / 'public'; public.mkdir()
    (public / 'robots.txt').write_text('User-agent: *\nAllow: /\n')
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(public))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    try:
        (tmp_path / 'index.html').write_text('Old content')
        job = growth.create(tmp_path, brief(url, tmp_path))
        with pytest.raises(ValueError, match='no declared source change'): growth.validate(tmp_path, job)
        html = f'<html><head><link rel="canonical" href="{url}/"></head><body>Tested deployment procedure</body></html>'
        (tmp_path / 'index.html').write_text(html)
        growth.validate(tmp_path, job); assert job['status'] == 'validated'
        with pytest.raises(ValueError, match='authorization'): growth.deploy(tmp_path, job)
        growth.deploy(tmp_path, job, approved=True)
        assert job['status'] == 'deployment_unverified'
        growth.verify(tmp_path, job); assert job['status'] == 'verified' and job['review_due']
        (public / 'robots.txt').write_text('User-agent: OAI-SearchBot\nDisallow: /\n')
        growth.verify(tmp_path, job); assert job['status'] == 'verification_failed'
        (tmp_path / 'index.html').write_text(html + ' changed')
        with pytest.raises(ValueError, match='source state changed'): growth.verify(tmp_path, job)
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_validation_failure_does_not_allow_deployment(tmp_path):
    (tmp_path / 'index.html').write_text('Old')
    job = growth.create(tmp_path, brief('https://fixture.test', tmp_path))
    (tmp_path / 'index.html').write_text('Still missing required content')
    growth.validate(tmp_path, job)
    assert job['status'] == 'validation_failed'
    with pytest.raises(ValueError): growth.deploy(tmp_path, job, approved=True)


def test_timeout_persists_uncertainty_before_effect_and_forbids_blind_retry(tmp_path, monkeypatch):
    (tmp_path / 'index.html').write_text('old')
    job = growth.create(tmp_path, brief('https://fixture.test', tmp_path))
    (tmp_path / 'index.html').write_text('Tested deployment procedure')
    growth.validate(tmp_path, job)
    saved = []
    def execute(root, brief, kind):
        assert saved[-1]['status'] == 'deployment_uncertain'
        return {'exit': None, 'uncertain': True}
    monkeypatch.setattr(growth, 'execute', execute)
    growth.deploy(tmp_path, job, True, persist=lambda j: saved.append(json.loads(json.dumps(j))))
    assert job['status'] == 'deployment_uncertain'
    with pytest.raises(ValueError): growth.deploy(tmp_path, job, True)
    with pytest.raises(ValueError): growth.validate(tmp_path, job)


def test_first_deployment_date_survives_delayed_verification(tmp_path, fake_transport):
    (tmp_path / 'index.html').write_text('old'); job = growth.create(tmp_path, brief('https://fixture.test', tmp_path))
    (tmp_path / 'index.html').write_text('Tested deployment procedure'); growth.validate(tmp_path, job)
    job.update(status='deployment_unverified', deployment_attempted_at='2026-01-01T12:00:00Z')
    fake_transport.route('GET','https://fixture.test/robots.txt', {'body':'User-agent: *\nAllow: /'})
    fake_transport.route('GET','https://fixture.test/', {'body':'<link rel="canonical" href="https://fixture.test/"><p>Tested deployment procedure</p>'})
    growth.verify(tmp_path, job)
    assert job['deployment_earliest'] == '2026-01-01' and job['first_verified_on'] > '2026-01-01'
    assert job['review_due'] > job['first_verified_on']


def test_codex_install_and_scheduled_packet_handoff(tmp_path):
    import os
    import subprocess
    import yaml
    engine = Path(__file__).resolve().parents[1]
    result = subprocess.run(['bash', str(engine/'install.sh'), str(engine), str(tmp_path), 'codex'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path/'.agents/skills/seo-growth/SKILL.md').is_file()
    config = tmp_path/'.seo-engine/config.yml'
    config.parent.mkdir(exist_ok=True)
    cfg = {}
    cfg['growth'] = {'agent_command': [sys.executable, '-c', "import json,sys; from pathlib import Path; p=json.loads(Path(sys.argv[1]).read_text()); assert p['jobs']==[]; Path('agent-ran.txt').write_text(p['skill'])"]}
    config.write_text(yaml.safe_dump(cfg))
    result = subprocess.run([sys.executable, str(engine/'skills/seo-growth/scripts/run_cycle.py'), '--execute-agent'],
        cwd=tmp_path, env={**os.environ, 'SEO_REPO_ROOT': str(tmp_path)}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path/'agent-ran.txt').read_text().endswith('seo-growth/SKILL.md')
    assert json.loads((tmp_path/'.seo-engine/reports/growth-cycle-last.json').read_text())['agent_ran']


def test_confirmed_non_deployment_can_be_reconciled_and_retried(tmp_path):
    (tmp_path/'index.html').write_text('Old')
    job = growth.create(tmp_path, brief('https://fixture.test', tmp_path))
    (tmp_path/'index.html').write_text('Tested deployment procedure')
    growth.validate(tmp_path, job)
    job.update(status='deployment_uncertain', deployment_attempted_at='2026-01-01T00:00:00Z', deployment={'exit': None})
    (tmp_path/'hosting-evidence.txt').write_text('Synthetic hosting audit log confirms job rejected before deployment.')
    growth.reconcile(tmp_path, job, {'decision':'confirmed_not_deployed', 'reviewer':'Fixture Operator',
        'reason':'The hosting API rejected authentication before creating a deployment.', 'evidence_file':'hosting-evidence.txt'})
    growth.validate(tmp_path, job)
    assert job['status'] == 'validated' and job['reconciliations'][0]['prior_result']['exit'] is None


def test_demand_comparison_rejects_assumptions_and_stale_evidence(tmp_path):
    from scripts.lib import opportunities
    candidates = brief('https://fixture.test', tmp_path)['selection']['candidates']
    for c in candidates: c['evidence'] = []
    result = opportunities.assess(candidates)
    assert result['suggested_id'] is None
    (tmp_path/'index.html').write_text('Old')
    b = brief('https://fixture.test', tmp_path); b['selection']['candidates'] = candidates
    with pytest.raises(ValueError, match='evidenced candidate'): growth.create(tmp_path,b)


def test_inconclusive_outcomes_remain_scheduled_and_record_cost_decision(tmp_path):
    from datetime import date, timedelta
    (tmp_path/'index.html').write_text('Old'); job = growth.create(tmp_path, brief('https://fixture.test', tmp_path))
    job.update(status='verified', deployment_earliest='2026-02-02', first_verified_on='2026-02-08')
    def export(start,end):
        return {'property':'fixture','timezone':'UTC','site_url':'https://fixture.test','exporter':'unit-test',
                'start':start,'end':end,'synthetic':True,'complete':True,'rows':[]}
    growth.evaluate(job, export('2026-01-05','2026-02-01'), export('2026-02-09','2026-03-08'))
    assert job['status'] == 'observing' and job['review_due']
    due = (date.today()+timedelta(days=21)).isoformat()
    growth.decide(job, {'reviewer':'Fixture Owner','decision':'defer','reason':'No traffic sample yet; wait for mature observations before judging.',
                        'costs':{'known':True,'human_minutes':30,'api_usd':0},'next_review':due})
    assert job['status'] == 'observing' and job['review_due'] == due and job['decisions'][0]['costs']['api_usd'] == 0


def test_local_evidence_hash_and_incomplete_paid_discovery(tmp_path, monkeypatch):
    from scripts.lib import opportunities
    candidates = brief('https://fixture.test', tmp_path)['selection']['candidates']
    (tmp_path/'evidence.txt').write_text('Synthetic evidence snapshot')
    candidates[0]['evidence'][0]['snapshot']='evidence.txt'
    result=opportunities.assess(candidates,root=tmp_path)
    assert result['candidates'][0]['accepted_evidence'][0]['snapshot_sha256']
    monkeypatch.setattr(opportunities.dataforseo,'search_volume',lambda *a: {'tasks':[{'result':[]}]})
    monkeypatch.setattr(opportunities.dataforseo,'serp_live',lambda *a: {'status_code':20000,'tasks':[{'status_code':20100,'result':None}]})
    result=opportunities.discover(None,['query'],2840,'en')
    assert not result['complete'] and result['queries'][0]['monthly_searches'] is None


def test_retain_inconclusive_outcome_requires_explicit_acknowledgement():
    job = {'status': 'observing', 'outcome': {'channels': {
        'google_organic': {'decision': 'insufficient_sample'},
        'chatgpt': {'decision': 'insufficient_sample'}}}, 'review_due': '2099-01-01'}
    record = {'reviewer': 'Fixture Owner', 'decision': 'retain', 'costs': {'known': False},
              'reason': 'Keep this useful reader correction despite inconclusive traffic observations.'}
    with pytest.raises(ValueError, match='close_without_traffic_evidence'):
        growth.decide(job, record)
    assert job['status'] == 'observing' and 'decisions' not in job
    growth.decide(job, {**record, 'close_without_traffic_evidence': True})
    assert job['status'] == 'closed'
    assert job['decisions'][-1]['traffic_conclusion'] == 'not_demonstrated'
    assert set(job['decisions'][-1]['inconclusive_channels']) == {'google_organic', 'chatgpt'}


def test_dynamic_product_route_build_deploy_verify(tmp_path):
    """Actual server-side dynamic route from deployed structured data, not a mocked fetch."""
    import html
    public = tmp_path/'public'; public.mkdir()
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            if self.path == '/robots.txt':
                body = 'User-agent: *\nAllow: /\n'; status = 200
            elif self.path == '/products/widget':
                product = json.loads((public/'product.json').read_text())
                body = f'<link rel="canonical" href="{url}/products/widget"><main><h1>{html.escape(product["name"])}</h1><p>{html.escape(product["guide"])}</p><span>${product["price"]}</span></main>'
                status = 200
            else: body, status = 'not found', 404
            self.send_response(status); self.end_headers(); self.wfile.write(body.encode())
    server = http.server.ThreadingHTTPServer(('127.0.0.1',0), Handler)
    url = f'http://127.0.0.1:{server.server_port}'
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        (tmp_path/'product.json').write_text(json.dumps({'name':'Widget','price':25,'guide':'Old summary'}))
        b = brief(url, tmp_path); b['source_files']=['product.json']; b['pages']=[{'path':'/products/widget','expected_text':'Tested deployment procedure','baseline_file':'product.json'}]
        for candidate in b['selection']['candidates']: candidate['page']='/products/widget'
        b['commands']={'test':[sys.executable,'-c',"import json; from pathlib import Path; p=json.loads(Path('product.json').read_text()); assert p['price']==25 and 'Tested deployment procedure' in p['guide']"],
                       'build':[sys.executable,'-c',"import json; from pathlib import Path; json.loads(Path('product.json').read_text())"],
                       'deploy':[sys.executable,'-c',"import shutil; shutil.copy('product.json','public/product.json')"]}
        job=growth.create(tmp_path,b)
        (tmp_path/'product.json').write_text(json.dumps({'name':'Widget','price':25,'guide':'Tested deployment procedure with real product instructions'}))
        growth.validate(tmp_path,job); growth.deploy(tmp_path,job,True); growth.verify(tmp_path,job)
        assert job['status']=='verified'
        product=json.loads((public/'product.json').read_text()); product['guide']='Old summary'; (public/'product.json').write_text(json.dumps(product))
        growth.verify(tmp_path,job); assert job['status']=='verification_failed'
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_existing_expected_phrase_cannot_verify_a_noop_change(tmp_path):
    (tmp_path/'index.html').write_text('<p>Tested deployment procedure</p><p>old information</p>')
    with pytest.raises(ValueError, match='already pass in the production baseline'):
        growth.create(tmp_path,brief('https://fixture.test', tmp_path))


def test_followup_creation_links_parent_and_prevents_duplicate_url(tmp_path):
    import os
    import subprocess
    (tmp_path/'index.html').write_text('Old content')
    parent=growth.create(tmp_path,brief('https://fixture.test', tmp_path)); parent['status']='followup_required'; parent['decisions']=[{'decision':'refine'}]
    folder=tmp_path/'.seo-engine/state/growth'; folder.mkdir(parents=True)
    (folder/'useful-guide.json').write_text(json.dumps(parent))
    b=brief('https://fixture.test', tmp_path); b['id']='refined-guide'; b['followup']={'decision':'refine','scope':'Improve the original guide with more useful deployment instructions.'}; path=tmp_path/'brief.json'; path.write_text(json.dumps(b))
    script=Path(__file__).resolve().parents[1]/'skills/seo-growth/scripts/run_growth.py'
    env={**os.environ,'SEO_REPO_ROOT':str(tmp_path)}
    result=subprocess.run([sys.executable,str(script),'--stage','create','--brief-file',str(path)],env=env,capture_output=True,text=True)
    assert result.returncode==1 and 'active intervention' in result.stdout
    result=subprocess.run([sys.executable,str(script),'--stage','create','--brief-file',str(path),'--parent-id','useful-guide'],env=env,capture_output=True,text=True)
    assert result.returncode==0, result.stdout+result.stderr
    assert json.loads((folder/'useful-guide.json').read_text())['status']=='followup_in_progress'
    assert json.loads((folder/'refined-guide.json').read_text())['parent_id']=='useful-guide'


def test_metadata_only_repair_and_stale_deploy(tmp_path, fake_transport):
    old='<link rel="canonical" href="https://fixture.test/"><meta name="robots" content="noindex"><p>Existing useful content stays unchanged.</p>'
    (tmp_path/'index.html').write_text(old); (tmp_path/'diagnostic.json').write_text('{"finding":"accidental noindex"}')
    (tmp_path/'public').mkdir()
    b=brief('https://fixture.test', tmp_path); b.update(kind='technical_repair',diagnostic_file='diagnostic.json')
    b.pop('selection')
    b['pages']=[{'path':'/','baseline_file':'index.html','assertions':[{'kind':'indexable','expected':True}]}]
    b['commands']['test']=[sys.executable,'-c',"from pathlib import Path; text=Path('index.html').read_text(); assert 'noindex' not in text and 'Existing useful content stays unchanged.' in text"]
    job=growth.create(tmp_path,b)
    new=old.replace('noindex','index'); (tmp_path/'index.html').write_text(new)
    growth.validate(tmp_path,job); growth.deploy(tmp_path,job,True)
    fake_transport.route('GET','https://fixture.test/robots.txt',{'body':'User-agent: *\nAllow: /'})
    fake_transport.route('GET','https://fixture.test/',{'body':old},{'body':new})
    growth.verify(tmp_path,job); assert job['status']=='verification_failed'
    growth.verify(tmp_path,job); assert job['status']=='verified'


def test_cancel_block_resume_preserves_uncertain_deployment_rules():
    from datetime import date,timedelta
    record={'reviewer':'Owner','reason':'The required product evidence is unavailable for this topic.'}
    job={'status':'planned'}
    growth.update_predeployment(job,{**record,'action':'block','next_review':(date.today()+timedelta(days=7)).isoformat()})
    assert job['status']=='blocked'
    growth.update_predeployment(job,{**record,'action':'resume'}); assert job['status']=='planned'
    growth.update_predeployment(job,{**record,'action':'cancel'}); assert job['status']=='cancelled'
    job['status']='deployment_uncertain'
    with pytest.raises(ValueError,match='reconciled'): growth.update_predeployment(job,{**record,'action':'cancel'})


def test_unrelated_followup_cannot_close_parent(tmp_path):
    (tmp_path/'index.html').write_text('Old'); parent=growth.create(tmp_path,brief('https://fixture.test', tmp_path))
    parent.update(status='followup_required',decisions=[{'decision':'revert'}])
    child={'brief':{**parent['brief'],'pages':[{'path':'/unrelated'}], 'followup':{'decision':'revert','scope':'An unrelated page is not an implementation of the requested rollback.'}}}
    with pytest.raises(ValueError,match='every affected'): growth.validate_followup(parent,child)
    child['brief']['pages']=parent['brief']['pages']; child['brief']['followup']['decision']='refine'
    with pytest.raises(ValueError,match='parent decision'): growth.validate_followup(parent,child)


def test_synthetic_data_cannot_drive_production_outcomes(tmp_path):
    (tmp_path/'index.html').write_text('Old'); job=growth.create(tmp_path,brief('https://fixture.test', tmp_path))
    job.update(status='verified',simulation=False)
    with pytest.raises(ValueError,match='synthetic exports'): growth.evaluate(job,{'synthetic':True},{'synthetic':True})
    job['outcome']={'synthetic':True}
    with pytest.raises(ValueError,match='synthetic outcomes'): growth.decide(job,{'decision':'retain'})


def test_cancelled_child_reopens_parent_for_replacement(tmp_path):
    import os, subprocess
    (tmp_path/'index.html').write_text('Old content')
    parent=growth.create(tmp_path,brief('https://fixture.test', tmp_path)); parent.update(status='followup_required',decisions=[{'decision':'refine'}])
    folder=tmp_path/'.seo-engine/state/growth'; folder.mkdir(parents=True); (folder/'useful-guide.json').write_text(json.dumps(parent))
    b=brief('https://fixture.test', tmp_path); b.update(id='child-one',followup={'decision':'refine','scope':'Improve the same guide with a tested original deployment example.'})
    path=tmp_path/'brief.json'; path.write_text(json.dumps(b))
    script=Path(__file__).resolve().parents[1]/'skills/seo-growth/scripts/run_growth.py'; env={**os.environ,'SEO_REPO_ROOT':str(tmp_path)}
    def run(*args):
        out=subprocess.run([sys.executable,str(script),*args],env=env,capture_output=True,text=True)
        assert out.returncode==0,out.stdout+out.stderr
    run('--stage','create','--brief-file',str(path),'--parent-id','useful-guide')
    update=tmp_path/'update.json'; update.write_text(json.dumps({'action':'cancel','reviewer':'Owner','reason':'The first proposed implementation is no longer the best option.'}))
    run('--stage','update','--id','child-one','--update-file',str(update))
    assert json.loads((folder/'useful-guide.json').read_text())['status']=='followup_required'
    b['id']='child-two'; path.write_text(json.dumps(b))
    run('--stage','create','--brief-file',str(path),'--parent-id','useful-guide')
    assert json.loads((folder/'useful-guide.json').read_text())['child_id']=='child-two'


def test_git_fingerprint_detects_undeclared_template_change(tmp_path):
    import subprocess
    subprocess.run(['git','init','-q',str(tmp_path)],check=True)
    (tmp_path/'index.html').write_text('Old'); (tmp_path/'template.html').write_text('Original template')
    b=brief('https://fixture.test', tmp_path); initial=growth.fingerprint(tmp_path,b)
    (tmp_path/'template.html').write_text('Changed shared template')
    assert growth.fingerprint(tmp_path,b)!=initial


def test_measurement_uses_analytics_timezone_and_site_prefix(tmp_path):
    (tmp_path/'index.html').write_text('Old'); b=brief('https://fixture.test/shop', tmp_path); job=growth.create(tmp_path,b)
    job.update(status='verified',deployment_earliest='2026-02-02',first_verified_on='2026-02-08',
               deployment_attempted_at='2026-02-02T01:00:00Z',verified_at='2026-02-08T12:00:00Z')
    def export(start,end,sessions):
        return {'property':'fixture','timezone':'America/Los_Angeles','site_url':'https://fixture.test/shop','exporter':'unit',
                'start':start,'end':end,'synthetic':True,'complete':True,'rows':[{'date':start,'page':'/shop/','source':'google','medium':'organic','sessions':sessions,'key_events':0}]}
    before=export('2026-01-05','2026-02-01',100); after=export('2026-02-09','2026-03-08',150)
    with pytest.raises(ValueError,match='ambiguous deployment'): growth.evaluate(job,before,after)
    job['deployment_attempted_at']='2026-02-03T12:00:00Z'
    growth.evaluate(job,before,after)
    assert job['outcome']['channels']['google_organic']['session_delta']==50
    assert job['outcome']['operational_evidence'] is False
