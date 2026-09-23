"""Record demand alternatives or explicitly query paid seed-keyword evidence."""
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
from scripts.lib import config as config_module  # noqa: E402

import argparse
import json
from scripts.lib import opportunities, pubstate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates-file')
    parser.add_argument('--seeds', help='Comma-separated seeds; requires --paid-discovery')
    parser.add_argument('--paid-discovery', action='store_true', help='Explicit paid DataForSEO search-volume and SERP calls')
    parser.add_argument('--location-code', type=int, default=2840)
    parser.add_argument('--language-code', default='en')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        if args.paid_discovery:
            if not args.seeds: parser.error('--paid-discovery requires --seeds')
            result = opportunities.discover(config_module.load(), [s.strip() for s in args.seeds.split(',') if s.strip()], args.location_code, args.language_code)
        else:
            if not args.candidates_file: parser.error('supply --candidates-file or explicit --paid-discovery')
            result = opportunities.assess(json.loads(Path(args.candidates_file).read_text()), root=config_module.load().repo_root)
        pubstate.save_json(Path(args.out), result)
        print(json.dumps({'checked': True, 'result': result, 'output': args.out}))
        return 1 if result.get('complete') is False else 0
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print(json.dumps({'checked': False, 'error': str(exc)})); return 1


if __name__ == '__main__':
    sys.exit(main())
