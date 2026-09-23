"""One-site setup, secret handling and portable fresh-clone installation."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.lib.config import Config, _parse_env_file

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '00-onboarding/seo-setup/scripts/onboard.py'
spec = importlib.util.spec_from_file_location('onboarding', SCRIPT)
onboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(onboard)


def test_onboarding_resumes_completes_and_preserves_site(tmp_path):
    cfg = Config(repo_root=tmp_path, site={'target_topics': ['keep']})
    assert onboard.status(cfg)['status'] == 'not_started'
    assert not (tmp_path / '.seo-engine').exists()  # status is read-only
    onboard.save(cfg, {'brand_name': 'Acme', 'site_url': 'https://acme.test'})
    with pytest.raises(ValueError, match='audience'):
        onboard.complete(cfg)
    reloaded = Config.load(tmp_path)
    assert onboard.status(reloaded)['status'] == 'in_progress'
    onboard.save(reloaded, {
        'audience': 'Operations leads', 'goals': ['Useful product evaluation'],
        'success_measure': 'Qualified inquiries', 'workflow': 'research-content',
        'next_action': 'Research a customer question',
        'integrations': {'dataforseo': {'status': 'deferred', 'note': 'Host browsing; volumes unknown'}},
    })
    with pytest.raises(ValueError, match='brand brief'):
        onboard.complete(reloaded)
    (tmp_path / onboard.KNOWLEDGE).write_text('Acme helps operations leads. Drafts need review.')
    assert onboard.complete(reloaded)['status'] == 'complete'
    before = (tmp_path / onboard.PROFILE).read_bytes()
    onboard.complete(reloaded)
    assert (tmp_path / onboard.PROFILE).read_bytes() == before
    onboard.save(reloaded, {'brand_name': 'Acme'})
    assert onboard.status(reloaded)['status'] == 'complete'
    with pytest.raises(ValueError, match='different site'):
        onboard.save(reloaded, {'site_url': 'https://another.test'})
    assert (tmp_path / onboard.PROFILE).read_bytes() == before
    onboard.save(reloaded, {'next_action': 'Review a new goal'})
    assert onboard.status(reloaded)['status'] == 'in_progress'


def test_onboarding_does_not_claim_missing_credentials_ready(tmp_path):
    cfg = Config(repo_root=tmp_path)
    onboard.save(cfg, {
        'brand_name': 'Acme', 'site_url': 'https://acme.test', 'audience': 'Buyers',
        'goals': ['Educate'], 'success_measure': 'Inquiries', 'workflow': 'existing-site',
        'next_action': 'Read GSC',
        'integrations': {'google_search_console': {'status': 'verified', 'note': 'Operator says connected'}},
    })
    (tmp_path / onboard.KNOWLEDGE).write_text('Acme brand brief')
    with pytest.raises(ValueError, match='credentials are missing'):
        onboard.complete(cfg)
    with pytest.raises(ValueError, match='Unknown onboarding fields'):
        onboard.save(cfg, {'status': 'complete'})


def test_credential_store_preserves_unrelated_data_and_hides_values(tmp_path):
    path = tmp_path / '.env'
    path.write_text('# Existing app\nAPP_SETTING=keep\nexport OPENROUTER_API_KEY=old\nOPENROUTER_API_KEY=duplicate\n')
    secret = 'secret-with-$() # spaces and "quotes"'
    result = onboard.store_credential(tmp_path, 'OPENROUTER_API_KEY', secret)
    assert secret not in json.dumps(result)
    values = _parse_env_file(path)
    assert values == {'APP_SETTING': 'keep', 'OPENROUTER_API_KEY': secret}
    assert path.read_text().count('OPENROUTER_API_KEY=') == 1
    assert path.stat().st_mode & 0o777 == 0o600
    assert '.env' in (tmp_path / '.gitignore').read_text().splitlines()
    onboard.store_credential(tmp_path, 'GSC_SERVICE_ACCOUNT_JSON', '{\n "type": "service_account"\n}')
    assert json.loads(_parse_env_file(path)['GSC_SERVICE_ACCOUNT_JSON'])['type'] == 'service_account'
    with pytest.raises(ValueError):
        onboard.store_credential(tmp_path, 'OPENROUTER_API_KEY', 'x\nEVIL=value')
    with pytest.raises(ValueError):
        onboard.store_credential(tmp_path, 'UNSUPPORTED', secret)


def test_credential_refuses_tracked_or_shared_env(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    path = tmp_path / '.env'
    path.write_text('APP_SETTING=keep\n')
    subprocess.run(['git', '-C', str(tmp_path), 'add', '.env'], check=True)
    with pytest.raises(ValueError, match='tracked'):
        onboard.store_credential(tmp_path, 'OPENROUTER_API_KEY', 'secret')
    assert path.read_text() == 'APP_SETTING=keep\n'
    path.unlink()
    path.symlink_to(tmp_path / 'elsewhere')
    with pytest.raises(ValueError, match='symlink'):
        onboard.store_credential(tmp_path, 'OPENROUTER_API_KEY', 'secret')


def test_default_install_targets_clone_and_optional_links_survive_rename(tmp_path):
    import shutil
    engine = tmp_path / 'fresh-clone'
    skill = engine / '00-onboarding/seo-setup'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('# minimal installation fixture')
    (engine / 'ARCHITECTURE.md').touch()
    shutil.copyfile(ROOT / 'install.sh', engine / 'install.sh')
    subprocess.run(['git', 'init', '-q', str(engine)], check=True)
    result = subprocess.run(['bash', str(engine / 'install.sh')], cwd=tmp_path, capture_output=True, text=True, check=True)
    assert 'Portable setup' in result.stdout
    assert (engine / '.env').exists() and not (tmp_path / '.env').exists()
    assert not (engine / '.claude').exists() and not (engine / '.agents').exists()
    for host, parent in [('codex', '.agents'), ('claude', '.claude')]:
        subprocess.run(['bash', str(engine / 'install.sh'), str(engine), str(engine), host], check=True, capture_output=True)
        assert not Path(os.readlink(engine / parent / 'skills/seo-setup')).is_absolute()
    moved = tmp_path / 'acme-seo'
    engine.rename(moved)
    for parent in ('.agents', '.claude'):
        assert (moved / parent / 'skills/seo-setup/SKILL.md').is_file()
    for private in ['.env', '.seo-engine/onboarding.json', 'credentials/google.json']:
        subprocess.run(['git', '-C', str(moved), 'check-ignore', private], check=True, capture_output=True)


def test_credential_file_cli_does_not_emit_secret(tmp_path):
    secret = 'test-token-for-local-fixture'
    credential_file = tmp_path / 'token'
    credential_file.write_text(secret)
    result = subprocess.run([sys.executable, str(SCRIPT), '--action', 'credential', '--key', 'OPENROUTER_API_KEY',
                             '--from-file', str(credential_file)], cwd=tmp_path,
                            env={**os.environ, 'SEO_REPO_ROOT': str(tmp_path)}, capture_output=True, text=True, check=True)
    assert secret not in result.stdout + result.stderr
    assert _parse_env_file(tmp_path / '.env')['OPENROUTER_API_KEY'] == secret
