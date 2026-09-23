"""Inspect the target, validate agent-authored strategy, or show the next missing section."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import os
_roots = ([Path(os.environ['SEO_ENGINE_ROOT'])] if os.environ.get('SEO_ENGINE_ROOT') else []) + list(Path(__file__).resolve().parents)
_engine = next((p for p in _roots if (p / 'scripts/lib/config.py').is_file()), None)
if _engine is None: raise SystemExit('Set SEO_ENGINE_ROOT to the complete engine directory')
sys.path.insert(0, str(_engine))
from scripts.lib import config as config_module
from scripts.lib import strategy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action', choices=['inspect', 'record', 'status'], default='status')
    parser.add_argument('--section', choices=strategy.SECTIONS)
    parser.add_argument('--file', help='Agent-authored section JSON; examples are in the workflow contract')
    args = parser.parse_args()
    cfg = config_module.load()
    try:
        if args.action == 'inspect': result = strategy.inspect_repo(cfg)
        elif args.action == 'record':
            if not args.section or not args.file: parser.error('record requires --section and --file')
            record = strategy.save(cfg, args.section, json.loads(Path(args.file).read_text()))
            result = {'section': args.section, 'digest': record['digest'], 'path': str(strategy.folder(cfg) / f'{args.section}.json')}
        else: result = strategy.status(cfg)
        print(json.dumps({'checked': True, 'result': result})); return 0
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
        print(json.dumps({'checked': False, 'error': str(exc)})); return 1


if __name__ == '__main__':
    sys.exit(main())
