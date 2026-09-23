"""Canonical phase-owned skill locations; legacy aliases are not runtime dependencies."""
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[2]


def skill(name):
    if name == 'seo-references': return ENGINE_ROOT / 'shared' / name
    matches = [p for p in ENGINE_ROOT.glob('0[1-6]-*/' + name) if (p / 'SKILL.md').is_file()]
    if len(matches) != 1: raise ValueError(f'Expected one phase directory for skill {name}')
    return matches[0]
