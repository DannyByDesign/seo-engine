"""Durable first-party intervention lifecycle. Commands are repo-owned argv arrays."""
from __future__ import annotations
import hashlib
import json
import re
import subprocess
import time
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from . import http_util, pubstate, robots, traffic, opportunities


def fingerprint(root, brief):
    hashes = {}
    names=set(brief['source_files'])
    # Bind all versioned dependencies in a Git repo, including files omitted from the brief.
    detected=subprocess.run(['git','rev-parse','--show-toplevel'],cwd=root,capture_output=True,text=True)
    if detected.returncode==0 and Path(detected.stdout.strip()).resolve()==root.resolve():
        listing=subprocess.run(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=root,capture_output=True,check=True)
        names.update(n for n in listing.stdout.decode().split('\0') if n and not n.startswith(('.seo-engine/','.agents/skills/','.claude/skills/')))
    for name in sorted(names):
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError('source file escapes repository')
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return hashlib.sha256(json.dumps({'files': hashes, 'brief': brief}, sort_keys=True).encode()).hexdigest()


def assertions_for(page):
    assertions = page.get('assertions') or ([{'kind':'text_present','expected':page['expected_text']}] if page.get('expected_text') else [])
    if not assertions:
        raise ValueError('each page requires an explicit change assertion')
    for a in assertions:
        if a.get('kind') not in ('text_present','text_absent','title','canonical','indexable','header','robots_allowed'):
            raise ValueError('unsupported change assertion')
        if a['kind'] in ('indexable','robots_allowed'):
            if not isinstance(a.get('expected'),bool): raise ValueError('indexable/robots assertions require boolean expected')
        elif not isinstance(a.get('expected'),str) or not a['expected'].strip():
            raise ValueError('assertions require a nonempty expected value')
        if a['kind'] == 'header' and not a.get('name'):
            raise ValueError('header assertion requires name')
        if a['kind'] == 'robots_allowed' and a.get('bot') not in ('Googlebot','OAI-SearchBot','Bingbot'):
            raise ValueError('robots assertion needs Googlebot, OAI-SearchBot or Bingbot')
    return assertions


def assertions_pass(page, raw, headers, url, policy=None):
    soup=BeautifulSoup(raw,'lxml')
    text=' '.join(soup.get_text(' ',strip=True).split())
    canonical=soup.find('link',rel='canonical')
    directives=' '.join([headers.get('X-Robots-Tag',''),*[m.get('content','') for m in soup.find_all('meta') if m.get('name','').lower() in ('robots','googlebot')]]).lower()
    results=[]
    for a in assertions_for(page):
        expected=a['expected']; kind=a['kind']
        if kind == 'text_present': okay=' '.join(expected.split()) in text
        elif kind == 'text_absent': okay=' '.join(expected.split()) not in text
        elif kind == 'title': okay=bool(soup.title and soup.title.get_text(strip=True)==expected)
        elif kind == 'canonical': okay=bool(canonical and canonical.get('href')==expected)
        elif kind == 'indexable': okay=('noindex' not in directives and 'none' not in directives)==expected
        elif kind == 'header': okay=headers.get(a['name'])==expected
        else: okay=policy is not None and policy.allowed(a['bot'],url)==expected
        results.append({'assertion':a,'pass':okay})
    return results


def create(root, brief):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', brief.get('id', '')):
        raise ValueError('id must use lowercase letters, numbers and hyphens')
    for key in ('hypothesis', 'reader_need', 'original_value', 'demand_evidence', 'rollback'):
        if not isinstance(brief.get(key), str) or len(brief[key].strip()) < 20:
            raise ValueError(f'brief requires substantive {key}')
    if brief.get('kind') == 'technical_repair':
        evidence=(root / brief.get('diagnostic_file','')).resolve()
        if not evidence.is_relative_to(root.resolve()) or not evidence.is_file() or not evidence.read_bytes():
            raise ValueError('technical repair requires a saved diagnostic_file inside the repo')
        assessment={'kind':'technical_repair','diagnostic_sha256':hashlib.sha256(evidence.read_bytes()).hexdigest(),
                    'interpretation':'Operator-reviewed diagnostic evidence; no keyword-demand comparison needed for repair.'}
    else:
        selection = brief.get('selection') or {}
        assessment = opportunities.assess(selection.get('candidates'), root=root)
        selected = next((c for c in assessment['candidates'] if c['id'] == selection.get('selected_id')), None)
        if not selected or selected['status'] != 'ready_for_editorial_selection' or len(selection.get('rationale', '')) < 30:
            raise ValueError('select an evidenced candidate and explain why it beats the alternatives')
        if selected['page'] not in [p['path'] for p in brief.get('pages', [])]:
            raise ValueError('selected opportunity URL must belong to the intervention')
        # Existing isolated diagnostic/legacy workflows remain usable. Once strategy is
        # adopted, bind content work to the current positioning instead of stale briefs.
        if (root / '.seo-engine/state/strategy/understand.json').exists():
            from . import strategy
            from .config import Config
            position = strategy.load_valid(Config(repo_root=root), 'position')
            if brief.get('position_digest') != position['digest']:
                raise ValueError('content brief must bind current position_digest')
            if not any(b['page'] in [p['path'] for p in brief['pages']] for b in position['data']['copy_briefs']):
                raise ValueError('positioning needs a copy brief for this intervention')
    if not isinstance(brief.get('simulation',False),bool):
        raise ValueError('simulation must be an explicit boolean')
    site = urlsplit(brief.get('site_url', ''))
    if site.scheme not in ('https', 'http') or not site.hostname:
        raise ValueError('brief requires absolute site_url')
    if brief.get('simulation') and site.hostname not in ('127.0.0.1','localhost','::1') and not site.hostname.endswith(('.test','.invalid')):
        raise ValueError('simulation jobs must use local or reserved test hosts')
    if not brief.get('source_files') or not brief.get('pages'):
        raise ValueError('brief requires source_files and pages')
    for page in brief['pages']:
        if not page.get('path', '').startswith('/') or page['path'].startswith('//') :
            raise ValueError('each page needs a relative path')
        assertions_for(page)
    for kind in ('test', 'build'):
        command(brief, kind)
    baselines = []
    for page in brief['pages']:
        url = brief['site_url'].rstrip('/') + page['path']
        if page.get('baseline_file'):
            snapshot = (root / page['baseline_file']).resolve()
            if not snapshot.is_relative_to(root.resolve()) or not snapshot.is_file():
                raise ValueError('baseline_file must be an existing repo-local production snapshot')
            raw, status, kind = snapshot.read_text(), page.get('baseline_status',200), 'supplied_snapshot'
            headers=page.get('baseline_headers',{})
        else:
            response = http_util.request('GET', url, cache_ttl=0)
            if response.status_code not in (200,404):
                raise ValueError('baseline must be a successful page or confirmed 404, not a blocked/error response')
            if response.url.rstrip('/') != url.rstrip('/'):
                raise ValueError('baseline redirects; resolve the intended canonical route before creating work')
            raw, status, kind = response.text, response.status_code, 'fetched_http'
            headers=response.headers
        policy=None
        if any(a['kind']=='robots_allowed' for a in assertions_for(page)):
            if page.get('baseline_file'):
                robotfile=(root / page.get('baseline_robots_file','')).resolve()
                if not robotfile.is_relative_to(root.resolve()) or not robotfile.is_file():
                    raise ValueError('supplied robots baseline requires baseline_robots_file')
                policy=robots.parse(robotfile.read_text())
            else: policy=robots.fetch(brief['site_url'])
        checks=assertions_pass(page,raw,headers,url,policy)
        if status==200 and all(c['pass'] for c in checks):
            raise ValueError('change assertions already pass in the production baseline; choose an actual before/after distinction')
        baselines.append({'url': url, 'status': status, 'kind': kind, 'sha256': hashlib.sha256(raw.encode()).hexdigest(),
                          'captured_at': pubstate.now_iso(), 'change_assertions': checks})
    return {'simulation': brief.get('simulation',False), 'baseline_checks': baselines, 'brief': brief, 'status': 'planned', 'created_at': pubstate.now_iso(),
            'demand_assessment': assessment, 'initial_fingerprint': fingerprint(root, brief), 'history': [], 'outcome': None}


def command(brief, kind):
    cmd = brief.get('commands', {}).get(kind)
    if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) and x for x in cmd):
        raise ValueError(f'configure commands.{kind} as a nonempty argv array')
    return cmd


def execute(root, brief, kind):
    # No shell interpolation. Configured commands are executable project code, not a sandbox.
    started = time.monotonic()
    try:
        proc = subprocess.run(command(brief, kind), cwd=root, capture_output=True, text=True, timeout=600)
        # Diagnostics can include secrets: provide a short sanitized tail, never credential values.
        output = http_util.sanitize_text((proc.stdout + proc.stderr)[-1500:])
        return {'command': kind, 'exit': proc.returncode, 'seconds': round(time.monotonic()-started, 2),
                'output_sha256': hashlib.sha256((proc.stdout + proc.stderr).encode()).hexdigest(),
                'diagnostic': output if proc.returncode else ''}
    except subprocess.TimeoutExpired:
        return {'command': kind, 'exit': None, 'uncertain': True, 'diagnostic': 'Command timed out; reconcile remote state before retry.',
                'seconds': round(time.monotonic()-started, 2)}
    except OSError as exc:
        return {'command': kind, 'exit': -1, 'diagnostic': http_util.sanitize_text(str(exc))[:300]}


def validate(root, job):
    if job['status'] not in ('planned', 'validation_failed', 'validated'):
        raise ValueError('create a new intervention for changes after a deployment attempt')
    brief = job['brief']
    before = fingerprint(root, brief)
    if before == job['initial_fingerprint']:
        raise ValueError('no declared source change; implement the selected opportunity first')
    checks = []
    for kind in ('test', 'build'):
        check = execute(root, brief, kind); checks.append(check)
        if check['exit'] != 0:
            job.update(status='validation_failed', checks=checks)
            return job
    after = fingerprint(root, brief)
    if before != after:
        raise ValueError('test/build changed declared sources; inspect and validate again')
    job.update(status='validated', validated_fingerprint=after, checks=checks, validated_at=pubstate.now_iso())
    return job


def deploy(root, job, approved=False, persist=None):
    if not approved:
        raise ValueError('deployment needs existing user authorization and --approve-deploy')
    if job['status'] not in ('validated', 'deploy_failed') or fingerprint(root, job['brief']) != job.get('validated_fingerprint'):
        raise ValueError('validate the current source state before deployment')
    command(job['brief'],'deploy')  # configuration errors cannot have deployed anything
    job.update(status='deployment_uncertain', deployment_attempted_at=pubstate.now_iso())
    if persist:
        persist(job)  # durable intent before a potentially successful remote side effect
    result = execute(root, job['brief'], 'deploy')
    job.update(status='deployment_unverified' if result['exit'] == 0 else 'deployment_uncertain', deployment=result)
    return job


def verify(root, job):
    if job['status'] not in ('deployment_unverified', 'deployment_uncertain', 'verification_failed', 'verified'):
        raise ValueError('run the authorized deployment before verification')
    brief = job['brief']
    if fingerprint(root, brief) != job.get('validated_fingerprint'):
        raise ValueError('source state changed since validation')
    checks = []
    policy = robots.fetch(brief['site_url'])
    for page in brief['pages']:
        url = brief['site_url'].rstrip('/') + page['path']
        response = http_util.request('GET', url, cache_ttl=0)
        soup = BeautifulSoup(response.text, 'lxml')
        canonical = soup.find('link', rel='canonical')
        directives = ' '.join([response.headers.get('X-Robots-Tag', ''), *[m.get('content', '') for m in soup.find_all('meta') if m.get('name', '').lower() in ('robots','googlebot')]]).lower()
        checks.append({'url': url, 'status': response.status_code,
                       'pass': response.status_code == 200 and response.url.rstrip('/') == url.rstrip('/')
                       and canonical is not None and canonical.get('href', '').rstrip('/') == url.rstrip('/')
                       and 'noindex' not in directives and 'none' not in directives
                       and all(c['pass'] for c in assertions_pass(page,response.text,response.headers,url,policy))
                       and all(policy.allowed(bot, url) for bot in ('Googlebot', 'OAI-SearchBot')),
                       'html_sha256': hashlib.sha256(response.content).hexdigest()})
    okay = all(c['pass'] for c in checks)
    job.update(status='verified' if okay else 'verification_failed', production_checks=checks)
    if okay and not job.get('first_verified_on'):
        job.update(deployment_earliest=job['deployment_attempted_at'][:10], first_verified_on=date.today().isoformat(),
                   verified_at=pubstate.now_iso(), review_due=(date.today()+timedelta(days=35)).isoformat())
    return job


def evaluate(job, before, after):
    if job['status'] not in ('verified', 'observing', 'awaiting_decision', 'evaluated'):
        raise ValueError('production verification required before outcome evaluation')
    if (before.get('synthetic') or after.get('synthetic')) and not job.get('simulation'):
        raise ValueError('synthetic exports cannot evaluate a production intervention')
    brief = job['brief']
    if before['site_url'].rstrip('/') != brief['site_url'].rstrip('/'):
        raise ValueError('analytics export is for another site')
    tz=ZoneInfo(before['timezone'])
    earliest, latest = job['deployment_earliest'], job['first_verified_on']
    if job.get('deployment_attempted_at') and job.get('verified_at'):
        earliest=datetime.fromisoformat(job['deployment_attempted_at'].replace('Z','+00:00')).astimezone(tz).date().isoformat()
        latest=datetime.fromisoformat(job['verified_at'].replace('Z','+00:00')).astimezone(tz).date().isoformat()
    if not before['end'] < earliest or not latest < after['start']:
        raise ValueError('exclude the entire ambiguous deployment interval from baseline and follow-up')
    pages=[urlsplit(brief['site_url'].rstrip('/')+p['path']).path for p in brief['pages']]
    controls=[urlsplit(brief['site_url'].rstrip('/')+p).path for p in brief.get('controls',[])]
    result = traffic.compare(before, after, pages, earliest, controls)
    result['operational_evidence']=not job.get('simulation',False)
    result['deployment_interval'] = {'earliest': earliest, 'first_verified': latest}
    inconclusive = any(c['decision'] == 'insufficient_sample' for c in result['channels'].values())
    job.update(status='observing' if inconclusive else 'awaiting_decision', outcome=result,
               review_due=(date.today()+timedelta(days=14)).isoformat() if inconclusive else date.today().isoformat())
    job.setdefault('observations', []).append(result)
    return job


def reconcile(root, job, record):
    if job['status'] not in ('deployment_uncertain', 'deployment_unverified', 'verification_failed'):
        raise ValueError('only an unresolved deployment can be reconciled')
    if record.get('decision') != 'confirmed_not_deployed' or len(record.get('reason', '')) < 30:
        raise ValueError('record a confirmed_not_deployed decision with substantive reason')
    if not record.get('reviewer'):
        raise ValueError('identify the accountable reconciler')
    evidence = (root / record.get('evidence_file', '')).resolve()
    if not evidence.is_relative_to(root.resolve()) or not evidence.is_file():
        raise ValueError('save hosting status evidence inside the repo and provide evidence_file')
    receipt = {**record, 'evidence_sha256': hashlib.sha256(evidence.read_bytes()).hexdigest(), 'at': pubstate.now_iso(),
               'prior_attempt': job.get('deployment_attempted_at'), 'prior_result': job.get('deployment')}
    job.setdefault('reconciliations', []).append(receipt)
    job.update(status='planned')
    for key in ('validated_fingerprint', 'deployment_earliest', 'first_verified_on', 'review_due', 'outcome'):
        job.pop(key, None)
    # Keep the initial pre-intervention fingerprint: unchanged local implementation may be retried after fixing hosting.
    return job


def decide(job, record):
    if job['status'] not in ('verified','observing','awaiting_decision'):
        raise ValueError('decisions require a verified intervention')
    if (job.get('outcome') or {}).get('synthetic') and not job.get('simulation'):
        raise ValueError('synthetic outcomes cannot close production work')
    decision = record.get('decision')
    if decision not in ('retain','refine','revert','defer') or len(record.get('reason','')) < 30 or not record.get('reviewer'):
        raise ValueError('record reviewer, decision and substantive reason')
    costs = record.get('costs') or {}
    if costs.get('known') is True:
        for key in ('human_minutes', 'api_usd'):
            value = costs.get(key)
            if isinstance(value, bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value < 0:
                raise ValueError('known costs require nonnegative finite human_minutes and api_usd')
    elif costs.get('known') is not False:
        raise ValueError('costs.known must explicitly distinguish measured cost from unknown')
    if decision == 'defer':
        due = date.fromisoformat(record.get('next_review',''))
        if due <= date.today(): raise ValueError('defer needs a future next_review date')
        job.update(status='observing', review_due=due.isoformat())
    else:
        if not job.get('outcome'): raise ValueError('measure outcomes before deciding retain/refine/revert; otherwise defer')
        incomplete = [name for name, channel in job['outcome'].get('channels', {}).items()
                      if channel['decision'] == 'insufficient_sample']
        if decision == 'retain' and incomplete:
            if record.get('close_without_traffic_evidence') is not True:
                raise ValueError('defer inconclusive outcomes or explicitly set close_without_traffic_evidence: true')
            record = {**record, 'traffic_conclusion': 'not_demonstrated', 'inconclusive_channels': incomplete}
        job.update(status='closed' if decision == 'retain' else 'followup_required')
    job.setdefault('decisions', []).append({**record, 'at': pubstate.now_iso()})
    return job


def update_predeployment(job, record):
    action=record.get('action')
    if len(record.get('reason',''))<20 or not record.get('reviewer'):
        raise ValueError('record reviewer and substantive reason')
    if action in ('cancel','block'):
        if job['status'] not in ('planned','validated','validation_failed','blocked'):
            raise ValueError('attempted deployments must be reconciled, not cancelled or blocked away')
        if action=='block':
            due=date.fromisoformat(record.get('next_review',''))
            if due<=date.today(): raise ValueError('blocked work needs a future next_review')
            job.update(status='blocked',review_due=due.isoformat())
        else: job.update(status='cancelled')
    elif action=='resume':
        if job['status']!='blocked': raise ValueError('only blocked work can resume')
        job.update(status='planned'); job.pop('validated_fingerprint',None)
    else: raise ValueError('action must be cancel, block or resume')
    job.setdefault('updates',[]).append({**record,'at':pubstate.now_iso()})
    return job


def validate_followup(parent, child):
    if parent['status']!='followup_required' or parent['brief']['site_url']!=child['brief']['site_url']:
        raise ValueError('parent must require follow-up on this site')
    required={p['path'] for p in parent['brief']['pages']}
    if not required <= {p['path'] for p in child['brief']['pages']}:
        raise ValueError('follow-up must address every affected parent URL')
    decisions=parent.get('decisions') or []
    intent=(child['brief'].get('followup') or {})
    if not decisions or intent.get('decision')!=decisions[-1]['decision'] or len(intent.get('scope',''))<30:
        raise ValueError('follow-up must state the parent decision and substantive implementation scope')
