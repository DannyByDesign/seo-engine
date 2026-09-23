"""Local, resumable onboarding and hidden credential entry. No network calls."""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import warnings
from datetime import datetime, timezone

ENGINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ENGINE))
from scripts.lib.config import Config, INTEGRATION_ENV_VARS, save_site_config

PROFILE = '.seo-engine/onboarding.json'
KNOWLEDGE = '.seo-engine/knowledge.md'
REQUIRED = ('brand_name', 'site_url', 'audience', 'success_measure', 'next_action')
WORKFLOWS = ('existing-site', 'research-content', 'publication')


def read_profile(root):
    path = root / PROFILE
    return json.loads(path.read_text()) if path.exists() else {}


def private_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('Refusing to replace a symlink with private workspace data.')
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def ignore_private_files(root):
    path = root / '.gitignore'
    text = path.read_text() if path.exists() else ''
    for pattern in ('.env', '.seo-engine/', 'credentials/'):
        if pattern not in text.splitlines():
            text = text.rstrip('\n') + '\n' + pattern + '\n'
    path.write_text(text)


def validate(profile):
    for key in REQUIRED:
        if not isinstance(profile.get(key), str) or not profile[key].strip():
            raise ValueError(f'Onboarding needs {key}.')
    goals = profile.get('goals')
    if not isinstance(goals, list) or not goals or not all(isinstance(x, str) and x.strip() for x in goals):
        raise ValueError('Onboarding needs a nonempty goals list.')
    if profile.get('workflow') not in WORKFLOWS:
        raise ValueError('Choose existing-site, research-content, or publication.')
    Config(repo_root=Path('.'), site={'site_url': profile['site_url']}).site_url
    choices = profile.get('integrations')
    if not isinstance(choices, dict):
        raise ValueError('integrations must map selected providers to decisions; {} means no APIs.')
    for key, decision in choices.items():
        if key not in INTEGRATION_ENV_VARS or not isinstance(decision, dict):
            raise ValueError('Unknown integration or invalid decision.')
        if decision.get('status') not in ('configured', 'verified', 'deferred', 'blocked'):
            raise ValueError(f'{key}: record configured, verified, deferred, or blocked.')
        if not isinstance(decision.get('note'), str) or not decision['note'].strip():
            raise ValueError(f'{key}: record the check performed or why it is deferred/blocked.')


def save(cfg, incoming):
    if not isinstance(incoming, dict):
        raise ValueError('Onboarding input must be an object.')
    old = read_profile(cfg.repo_root)
    # Only these fields are accepted; completion cannot be forged through --file.
    allowed = set(REQUIRED) | {'goals', 'workflow', 'integrations', 'constraints', 'workspace_name'}
    if set(incoming) - allowed:
        raise ValueError('Unknown onboarding fields; keep secrets and raw interviews out of this file.')
    profile = {**old, **incoming}
    site = profile.get('site_url')
    established = cfg.site.get('site_url') or old.get('site_url')
    if site and established and site.rstrip('/') != established.rstrip('/'):
        raise ValueError('This workspace belongs to a different site. Use a fresh workspace for another site; handle domain migrations explicitly.')
    if site:
        site = Config(repo_root=cfg.repo_root, site={'site_url': site}).site_url
        profile['site_url'] = site
    if profile != old:
        profile.pop('completed_at', None)
        profile['status'] = 'in_progress'
    ignore_private_files(cfg.repo_root)
    private_write(cfg.repo_root / PROFILE, json.dumps(profile, indent=2) + '\n')
    if site:
        save_site_config(cfg, {'site_url': site})
    return status(cfg)


def complete(cfg):
    profile = read_profile(cfg.repo_root)
    validate(profile)
    if cfg.site_url != profile['site_url'].rstrip('/'):
        raise ValueError('Workspace config and onboarding site differ; reconcile them first.')
    if not (cfg.repo_root / KNOWLEDGE).is_file() or not (cfg.repo_root / KNOWLEDGE).read_text().strip():
        raise ValueError('Save the agreed brand brief in .seo-engine/knowledge.md first.')
    for key, choice in profile['integrations'].items():
        if choice['status'] in ('configured', 'verified') and not cfg.integration_available(key):
            raise ValueError(f'{key}: credentials are missing; configure it or record a deferral.')
    profile['status'] = 'complete'
    profile.setdefault('completed_at', datetime.now(timezone.utc).isoformat())
    private_write(cfg.repo_root / PROFILE, json.dumps(profile, indent=2) + '\n')
    return status(cfg)


def status(cfg):
    profile = read_profile(cfg.repo_root)
    choices = profile.get('integrations', {})
    return {
        'workspace': str(cfg.repo_root),
        'status': profile.get('status', 'not_started'),
        'profile_file': PROFILE,
        'knowledge_file': KNOWLEDGE,
        'brand_name': profile.get('brand_name'),
        'site_url': profile.get('site_url'),
        'workflow': profile.get('workflow'),
        'next_action': profile.get('next_action'),
        'integrations': {key: {'decision': row.get('status'), 'credentials_present': cfg.integration_available(key)}
                         for key, row in choices.items()},
        'note': 'Credential presence is not a successful API check. Resume incomplete setup; otherwise read the brand brief and continue the next action.',
    }


def store_credential(root, key, value):
    allowed = {v for spec in INTEGRATION_ENV_VARS.values() for vars_ in spec.values() for v in vars_}
    allowed |= {'LANGUAGETOOL_USERNAME', 'LANGUAGETOOL_API_KEY', 'OTTERLY_PROJECT_ID'}
    if key not in allowed:
        raise ValueError('Unsupported credential key; see .env.example for settings.')
    if key == 'GSC_SERVICE_ACCOUNT_JSON':
        try:
            value = json.dumps(json.loads(value), separators=(',', ':'))
        except ValueError:
            raise ValueError('Credential file must contain valid JSON.') from None
    if not value.strip() or any(c in value for c in ('\n', '\r', '\0')):
        raise ValueError('Credential must be nonempty and fit on one line.')
    path = root / '.env'
    if path.is_symlink():
        raise ValueError('Refusing a symlinked .env; use a workspace-local file.')
    tracked = subprocess.run(['git', '-C', str(root), 'ls-files', '--error-unmatch', '--', '.env'],
                             capture_output=True)
    if tracked.returncode == 0:
        raise ValueError('.env is tracked by Git. Untrack it before storing credentials.')
    original = path.read_text() if path.exists() else ''
    kept = [line for line in original.splitlines() if not re.match(r'^\s*(?:export\s+)?' + re.escape(key) + r'\s*=', line)]
    # The engine parser strips the outer pair only; it does not interpolate shell syntax.
    kept.append(f'{key}="{value}"')
    ignore_private_files(root)
    private_write(path, '\n'.join(kept) + '\n')
    return {'saved': key, 'file': '.env', 'note': 'Value hidden; run the selected integration check next.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action', choices=['status', 'save', 'complete', 'credential'], default='status')
    parser.add_argument('--file', type=Path, help='Agent-written onboarding JSON (not secrets) for save.')
    parser.add_argument('--key', help='Credential environment variable name; never pass the value in argv.')
    parser.add_argument('--from-file', type=Path, help='Read a user-selected credential file without displaying it.')
    args = parser.parse_args()
    cfg = Config.load()
    try:
        if args.action == 'save':
            if not args.file:
                raise ValueError('save needs --file.')
            result = save(cfg, json.loads(args.file.read_text()))
        elif args.action == 'complete':
            result = complete(cfg)
        elif args.action == 'credential':
            if not args.key:
                raise ValueError('credential needs --key.')
            if args.from_file:
                value = args.from_file.read_text().strip()
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter('error', getpass.GetPassWarning)
                    value = getpass.getpass(f'{args.key} (hidden): ')
            result = store_credential(cfg.repo_root, args.key, value)
        else:
            result = status(cfg)
    except (ValueError, OSError, RuntimeError, getpass.GetPassWarning, EOFError):
        # Avoid printing credential-bearing parser/network exceptions or input contents.
        if args.action == 'credential':
            print(json.dumps({'error': 'Credential not saved. Check key/file, use a local untracked .env, and use a user-controlled terminal for hidden entry.'}))
        else:
            raise
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
