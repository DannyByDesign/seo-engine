"""Physical ownership and installed behavior after the six-phase migration."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from scripts.lib import paths

ROOT = Path(__file__).resolve().parents[1]


def test_every_skill_has_one_physical_phase_owner_and_legacy_alias():
    actual = [p.parent for p in ROOT.glob('0[0-6]-*/*/SKILL.md')]
    assert len(actual) == 26 and len({p.name for p in actual}) == 26
    assert paths.skill('seo-setup') == ROOT / '00-onboarding/seo-setup'
    assert not (ROOT / '01-understand/seo-setup').exists()
    for directory in actual:
        assert not directory.is_symlink()
        assert paths.skill(directory.name) == directory
        alias = ROOT / 'skills' / directory.name
        assert alias.is_symlink() and alias.resolve() == directory
    for name, phase in [('run_strategy.py', '01-understand'), ('research_market.py', '02-research'), ('run_cycle.py', '06-learn'), ('traffic_report.py', '06-learn')]:
        assert not (ROOT / phase / 'scripts' / name).is_symlink()
        assert (ROOT / 'skills/seo-growth/scripts' / name).resolve() == ROOT / phase / 'scripts' / name


def test_installer_and_canonical_commands_work_from_foreign_repo(tmp_path):
    subprocess.run(['bash', str(ROOT / 'install.sh'), str(ROOT), str(tmp_path), 'codex'], check=True, capture_output=True)
    installed = tmp_path / '.agents/skills'
    assert len(list(installed.iterdir())) == 27
    for link in installed.iterdir():
        assert link.is_symlink() and '/skills/' not in os.readlink(link)
    out = subprocess.run([sys.executable, str(ROOT / '01-understand/scripts/run_strategy.py'), '--action', 'inspect'],
                         cwd=tmp_path, capture_output=True, text=True, check=True)
    payload = json.loads(out.stdout)
    assert payload['checked'] and payload['result']['repo_root'] == str(tmp_path)
    samples = subprocess.run([sys.executable, str(installed / 'seo-copywriting/scripts/writing_examples.py'), '--mode', 'landing'],
                             cwd=tmp_path, capture_output=True, text=True, check=True)
    assert 'Human reference' in samples.stdout and 'Product explanation' in samples.stdout
    again = subprocess.run(['bash', str(ROOT / 'install.sh'), str(ROOT), str(tmp_path), 'codex'], check=True, capture_output=True, text=True)
    assert 'Linked 0 skill(s)' in again.stdout


def test_installer_migrates_old_onboarding_link(tmp_path):
    installed = tmp_path / '.agents/skills'
    installed.mkdir(parents=True)
    link = installed / 'seo-setup'
    link.symlink_to(ROOT / '01-understand/seo-setup')
    subprocess.run(['bash', str(ROOT / 'install.sh'), str(ROOT), str(tmp_path), 'codex'],
                   check=True, capture_output=True)
    assert link.resolve() == ROOT / '00-onboarding/seo-setup'
    assert (link / 'scripts/onboard.py').is_file()


def test_cross_phase_publication_dispatch_uses_actual_research_directory():
    filename = ROOT / '05-execute/pub-publish/scripts/run_pipeline.py'
    spec = importlib.util.spec_from_file_location('phase_pipeline', filename)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    args = SimpleNamespace(publications_dir=None, candidates=2, approve=False, indexnow=False)
    command = mod.step_command('research', 'fixture', 'draft', args)
    assert command[1] == str(ROOT / '02-research/pub-research/scripts/research_outline.py')
    assert Path(command[1]).is_file()
