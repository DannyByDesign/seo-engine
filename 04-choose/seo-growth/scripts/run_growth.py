"""Resume a recorded first-party growth intervention."""
from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info < (3, 9):
    sys.exit("seo-engine requires Python 3.9+ (found %d.%d)" % sys.version_info[:2])


def _find_engine_root(start: Path) -> Path:
    import os

    env = os.environ.get("SEO_ENGINE_ROOT")
    if env and (Path(env) / "scripts" / "lib" / "config.py").is_file():
        return Path(env)
    for candidate in [start, *start.parents]:
        if (candidate / "scripts" / "lib" / "config.py").is_file():
            return candidate
    raise SystemExit(
        "Could not locate seo-engine root (scripts/lib/config.py). If skills were "
        "copied (not symlinked), set SEO_ENGINE_ROOT=/path/to/seo-engine."
    )


sys.path.insert(0, str(_find_engine_root(Path(__file__).resolve())))
from scripts.lib import config as config_module

import argparse
import fcntl
import json
import re
import subprocess
from datetime import date
from scripts.lib import growth, traffic, pubstate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['create','status','validate','deploy','verify','evaluate','reconcile','decide','update'], default='status')
    parser.add_argument('--id')
    parser.add_argument('--parent-id')
    parser.add_argument('--brief-file')
    parser.add_argument('--reconciliation-file')
    parser.add_argument('--decision-file')
    parser.add_argument('--update-file')
    parser.add_argument('--approve-deploy', action='store_true')
    parser.add_argument('--before')
    parser.add_argument('--after')
    args = parser.parse_args()
    cfg = config_module.load()
    folder = cfg.state_dir / 'growth'; folder.mkdir(exist_ok=True)
    with (folder / '.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'checked': False, 'error': 'another growth run is active'})); return 1
        try:
            if args.stage == 'status' and not args.id:
                jobs = [json.loads(p.read_text()) for p in sorted(folder.glob('*.json'))]
                print(json.dumps({'checked': True, 'jobs': [{'id': j['brief']['id'], 'status': j['status'], 'simulation': j.get('simulation',False),
                    'review_due': j.get('review_due'), 'overdue': bool(j.get('review_due') and j['review_due'] <= date.today().isoformat() and j['status'] not in ('closed','superseded','cancelled'))} for j in jobs]})); return 0
            if args.stage == 'create':
                if not args.brief_file: parser.error('--create requires --brief-file')
                job = growth.create(cfg.repo_root, json.loads(Path(args.brief_file).read_text()))
                path = folder / (job['brief']['id'] + '.json')
                if path.exists(): raise ValueError('intervention already exists; resume by --id')
                if args.parent_id:
                    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}',args.parent_id): parser.error('invalid --parent-id')
                    parent_path=folder/(args.parent_id+'.json'); parent=json.loads(parent_path.read_text())
                    growth.validate_followup(parent,job)
                    job['parent_id']=args.parent_id
                for other_path in folder.glob('*.json'):
                    other=json.loads(other_path.read_text())
                    if other['status'] not in ('closed','superseded','cancelled') and other['brief']['id'] != args.parent_id:
                        if other['brief']['site_url'] == job['brief']['site_url'] and {p['path'] for p in other['brief']['pages']} & {p['path'] for p in job['brief']['pages']}:
                            raise ValueError('another active intervention owns this URL; resume or link its follow-up')

            else:
                if not args.id or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', args.id):
                    parser.error('a valid --id is required')
                path = folder / (args.id + '.json')
                job = json.loads(path.read_text())
                if args.stage == 'validate': growth.validate(cfg.repo_root, job)
                elif args.stage == 'deploy': growth.deploy(cfg.repo_root, job, args.approve_deploy, persist=lambda record: pubstate.save_json(path, record))
                elif args.stage == 'verify': growth.verify(cfg.repo_root, job)
                elif args.stage == 'update':
                    if not args.update_file: parser.error('update requires --update-file')
                    growth.update_predeployment(job,json.loads(Path(args.update_file).read_text()))
                elif args.stage == 'decide':
                    if not args.decision_file: parser.error('decide requires --decision-file')
                    growth.decide(job, json.loads(Path(args.decision_file).read_text()))
                elif args.stage == 'reconcile':
                    if not args.reconciliation_file: parser.error('reconcile requires --reconciliation-file')
                    growth.reconcile(cfg.repo_root, job, json.loads(Path(args.reconciliation_file).read_text()))
                elif args.stage == 'evaluate':
                    if not args.before or not args.after: parser.error('evaluate requires --before and --after')
                    growth.evaluate(job, traffic.read_export(args.before), traffic.read_export(args.after))
            if args.stage != 'status':
                job['history'].append({'stage': args.stage, 'at': pubstate.now_iso(), 'status': job['status']})
                pubstate.save_json(path, job)
                if args.stage == 'create' and args.parent_id:
                    parent.update(status='followup_in_progress', child_id=job['brief']['id'])
                    pubstate.save_json(parent_path,parent)
                if args.stage == 'update' and job['status'] == 'cancelled' and job.get('parent_id'):
                    parent_path=folder/(job['parent_id']+'.json'); parent=json.loads(parent_path.read_text())
                    if parent.get('child_id')==job['brief']['id'] and parent['status']=='followup_in_progress':
                        parent.setdefault('cancelled_children',[]).append({'id':job['brief']['id'],'at':pubstate.now_iso()})
                        parent.update(status='followup_required'); parent.pop('child_id',None)
                        pubstate.save_json(parent_path,parent)
                if args.stage == 'verify' and job['status'] == 'verified' and job.get('parent_id'):
                    parent_path=folder/(job['parent_id']+'.json'); parent=json.loads(parent_path.read_text())
                    parent.update(status='superseded', child_id=job['brief']['id'], followup_verified_at=pubstate.now_iso())
                    pubstate.save_json(parent_path,parent)

            print(json.dumps({'checked': True, 'job': job, 'state_file': str(path)}))
            return 1 if job['status'].endswith(('_failed', '_uncertain')) else 0
        except (ValueError, KeyError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
            print(json.dumps({'checked': False, 'error': str(exc)})); return 1


if __name__ == '__main__':
    sys.exit(main())
