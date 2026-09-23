"""Install a real packaged engine into a foreign website without live network calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def archive(tmp_path):
    package = tmp_path / 'engine.tar.gz'
    # Include uncommitted package additions during development, never ignored runtime data.
    files = subprocess.check_output(['git', 'ls-files', '-co', '--exclude-standard'], cwd=ROOT, text=True).splitlines()
    with tarfile.open(package, 'w:gz', dereference=False) as bundle:
        for name in sorted(set(files)):
            path = ROOT / name
            if path.exists() or path.is_symlink():
                bundle.add(path, arcname='engine/' + name, recursive=False)
    return package


def setup_website(tmp_path, archive):
    site = tmp_path / 'website with spaces'
    site.mkdir()
    subprocess.run(['git', 'init', '-q', str(site)], check=True)
    (site / 'AGENTS.md').write_text('# Website\nPreserve our project rules.\n')
    (site / 'CLAUDE.md').write_text('Existing Claude instructions.\n')
    (site / '.env').write_text('APP_SECRET=original\n')
    (site / '.seo-engine').mkdir()
    (site / '.seo-engine/knowledge.md').write_text('Only this brand owns this knowledge.')
    (site / '.seo-engine/onboarding.json').write_text('{"status":"complete"}')
    (site / '.seo-engine/venv').mkdir()
    (site / '.seo-engine/venv/keep').touch()
    mock_bin = tmp_path / 'bin'
    mock_bin.mkdir()
    curl = mock_bin / 'curl'
    curl.write_text(f'''#!{sys.executable}
import json, os, shutil, sys
if any('api.github.com' in arg for arg in sys.argv):
    print(json.dumps({{'sha': os.environ.get('INSTALL_TEST_SHA', 'a' * 40)}}))
else:
    if os.environ.get('INSTALL_TEST_FAIL'):
        sys.exit(22)
    shutil.copyfile(os.environ['INSTALL_TEST_ARCHIVE'], sys.argv[sys.argv.index('-o') + 1])
''')
    curl.chmod(0o755)
    env = {**os.environ, 'PATH': str(mock_bin) + os.pathsep + os.environ['PATH'],
           'INSTALL_TEST_ARCHIVE': str(archive)}
    return site, env


def run_install(site, env, *args):
    return subprocess.run(['bash', str(ROOT / 'bootstrap.sh'), *args], cwd=site, env=env,
                          text=True, capture_output=True)


def test_direct_install_rerun_and_update_preserve_website(tmp_path, archive):
    site, env = setup_website(tmp_path, archive)
    original_git = (site / '.git/config').read_bytes()
    result = run_install(site, env, '--agent', 'codex')
    assert result.returncode == 0, result.stderr
    engine = site / '.seo-engine/engine'
    assert (engine / '05-execute/seo-copywriting/corpus/passages.md').is_file()
    assert (site / '.agents/skills/seo-setup/SKILL.md').is_file()
    assert (engine / '.installed-by-bootstrap').read_text().strip() == 'a' * 40
    (engine / 'old-installed-file').touch()
    # Re-running setup is idempotent and makes no download request.
    again = run_install(site, {**env, 'INSTALL_TEST_FAIL': '1'}, '--agent', 'codex')
    assert again.returncode == 0, again.stderr
    assert (site / 'AGENTS.md').read_text().count('<!-- BEGIN SEO ENGINE -->') == 1
    # Updating replaces engine files, not site state, secrets, instructions or its Python env.
    updated = run_install(site, {**env, 'INSTALL_TEST_SHA': 'b' * 40}, '--update', '--agent', 'codex')
    assert updated.returncode == 0, updated.stderr
    assert not (engine / 'old-installed-file').exists()
    assert (engine / '.installed-by-bootstrap').read_text().strip() == 'b' * 40
    assert (site / '.env').read_text() == 'APP_SECRET=original\n'
    assert (site / '.seo-engine/knowledge.md').read_text() == 'Only this brand owns this knowledge.'
    assert (site / '.seo-engine/onboarding.json').read_text() == '{"status":"complete"}'
    assert (site / '.seo-engine/venv/keep').exists()
    assert (site / 'AGENTS.md').read_text().startswith('# Website\nPreserve our project rules.')
    assert (site / 'CLAUDE.md').read_text().startswith('Existing Claude instructions.')
    assert (site / '.git/config').read_bytes() == original_git
    assert not list((site / '.seo-engine').glob('.install-*'))
    # The downloaded shared library and corpus execute from the website, not the package root.
    result = subprocess.run([sys.executable, str(engine / '01-understand/scripts/run_strategy.py'), '--action', 'inspect'],
                            cwd=site, text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)['result']['repo_root'] == str(site)
    result = subprocess.run([sys.executable, str(engine / '05-execute/seo-copywriting/scripts/writing_examples.py'), '--mode', 'landing'],
                            cwd=site, text=True, capture_output=True, check=True)
    assert 'Human reference' in result.stdout


def test_failed_download_keeps_current_install(tmp_path, archive):
    site, env = setup_website(tmp_path, archive)
    assert run_install(site, env).returncode == 0
    result = run_install(site, {**env, 'INSTALL_TEST_FAIL': '1'}, '--update')
    assert result.returncode != 0
    assert (site / '.seo-engine/engine/.installed-by-bootstrap').read_text().strip() == 'a' * 40
    assert (site / '.seo-engine/knowledge.md').is_file()
    assert not list((site / '.seo-engine').glob('.install-*'))


def test_direct_install_refuses_unmanaged_or_shared_engine(tmp_path, archive):
    site, env = setup_website(tmp_path, archive)
    engine = site / '.seo-engine/engine'
    engine.mkdir()
    (engine / 'personal-file').write_text('keep')
    result = run_install(site, env, '--update')
    assert result.returncode != 0 and 'not managed' in result.stderr
    assert (engine / 'personal-file').read_text() == 'keep'
    (engine / 'personal-file').unlink()
    engine.rmdir()
    engine.symlink_to(tmp_path / 'shared')
    result = run_install(site, env)
    assert result.returncode != 0 and 'symlinked' in result.stderr


def test_plugin_package_has_valid_skills_and_consistent_identity():
    codex = json.loads((ROOT / '.codex-plugin/plugin.json').read_text())
    claude = json.loads((ROOT / '.claude-plugin/plugin.json').read_text())
    assert codex['name'] == claude['name'] == 'seo-engine'
    assert codex['version'] == claude['version']
    for filename in ('.agents/plugins/marketplace.json', '.claude-plugin/marketplace.json'):
        market = json.loads((ROOT / filename).read_text())
        assert market['name'] == 'seo-engine'
        assert market['plugins'][0]['name'] == codex['name']
    skills = list((ROOT / 'skills').glob('*/SKILL.md'))
    assert len(skills) == 27
    for skill in skills:
        metadata = yaml.safe_load(skill.read_text().split('---', 2)[1])
        assert metadata['name'] == skill.parent.name
        assert isinstance(metadata['description'], str)
        assert skill.resolve().is_relative_to(ROOT)
