"""Export real referral traffic or compare attributable landing-page cohorts."""
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
import json
from scripts.lib import traffic, ga4, pubstate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ga4', action='store_true', help='Export actual GA4 traffic')
    parser.add_argument('--start')
    parser.add_argument('--end')
    parser.add_argument('--out', required=True)
    parser.add_argument('--before')
    parser.add_argument('--after')
    parser.add_argument('--pages', help='Comma-separated site-relative paths')
    parser.add_argument('--controls', default='')
    parser.add_argument('--deployed-on')
    args = parser.parse_args()
    try:
        if args.ga4:
            if not args.start or not args.end:
                parser.error('--ga4 requires --start and --end')
            result = ga4.export(config_module.load(), args.start, args.end)
        else:
            if not all((args.before, args.after, args.pages, args.deployed_on)):
                parser.error('comparison requires --before, --after, --pages and --deployed-on')
            result = traffic.compare(traffic.read_export(args.before), traffic.read_export(args.after),
                                     args.pages.split(','), args.deployed_on, [p for p in args.controls.split(',') if p])
        pubstate.save_json(Path(args.out), result)
        print(json.dumps({'checked': True, 'output': args.out, 'result': result}))
        return 0
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print(json.dumps({'checked': False, 'error': str(exc)})); return 1


if __name__ == '__main__':
    sys.exit(main())
