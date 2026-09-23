"""Read frozen human writing examples or check provenance and draft overlap."""
import argparse
import json
import os
import sys
from pathlib import Path

override = os.environ.get('SEO_ENGINE_ROOT')
candidates = ([Path(override)] if override else []) + list(Path(__file__).resolve().parents)
root = next((p for p in candidates if (p / 'scripts/lib/writing.py').is_file()), None)
if root is None: raise SystemExit('Set SEO_ENGINE_ROOT=/path/to/seo-engine when copying skills, or use installed symlinks.')
sys.path.insert(0, str(root))
from scripts.lib import writing


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=writing.MODES, default='article')
    p.add_argument('--seed', default='', help='Use the target page/topic to vary the reference packet')
    p.add_argument('--limit', type=int, default=6)
    p.add_argument('--verify', action='store_true')
    p.add_argument('--text-file', help='Check a local draft for exact copying from examples')
    args = p.parse_args()
    try:
        result = writing.verify() if args.verify else writing.overlap(Path(args.text_file).read_text()) if args.text_file else writing.packet(args.mode,args.seed,args.limit)
    except (ValueError, OSError) as exc:
        result = {'checked': False, 'error': str(exc)}
    print(writing.render_packet(result) if 'examples' in result and isinstance(result['examples'], list) else json.dumps(result,ensure_ascii=False))
    return 1 if result.get('checked') is False else 0


if __name__ == '__main__': sys.exit(main())
