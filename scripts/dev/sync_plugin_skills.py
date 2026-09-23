"""Generate real plugin entry files; plugin caches may omit symbolic links."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[2]


def sync(check=False):
    stale = []
    sources = sorted(ROOT.glob('0[0-6]-*/*/SKILL.md')) + [ROOT / 'shared/seo-references/SKILL.md']
    for source in sources:
        target = ROOT / 'skills' / source.parent.name
        frontmatter = source.read_text().split('---', 2)[1]
        relative = os.path.relpath(source, target)
        text = f'''---{frontmatter}---

# {source.parent.name}

Read [{source.parent.name} instructions]({relative}) and follow that skill before acting.
Resolve its scripts and references from that canonical directory, not this discovery adapter.
Run commands from the user's website repository; keep all site-specific state there.
'''
        entry = target / 'SKILL.md'
        if target.is_symlink() or not entry.is_file() or entry.read_text() != text:
            stale.append(source.parent.name)
            if not check:
                if target.is_symlink():
                    target.unlink()
                target.mkdir(exist_ok=True)
                entry.write_text(text)
        # Preserve old CLI paths for local users. Native plugin entry files always route
        # to canonical sources and never depend on these compatibility links.
        if not check:
            for item in source.parent.iterdir():
                if item.name == 'SKILL.md' or item.name.startswith(('.', '__')):
                    continue
                link = target / item.name
                if not link.exists() and not link.is_symlink():
                    link.symlink_to(os.path.relpath(item, target))
    if check and stale:
        print('Run python3 scripts/dev/sync_plugin_skills.py; stale entries: ' + ', '.join(stale))
        return 1
    print(f'Plugin entry files: {len(sources)} checked' if check else f'Plugin entry files: {len(sources)} generated')
    return 0


if __name__ == '__main__':
    sys.exit(sync(check='--check' in sys.argv))
