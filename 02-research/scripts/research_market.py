"""Collect specialized organic-growth data from real vendor APIs."""
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
from scripts.lib import research


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--provider', required=True, choices=research.OPERATIONS)
    p.add_argument('--operation', required=True, choices=sorted({x for xs in research.OPERATIONS.values() for x in xs}))
    p.add_argument('--query')
    p.add_argument('--target')
    p.add_argument('--location', type=int, default=2840)
    p.add_argument('--language', default='en')
    p.add_argument('--country', default='US')
    p.add_argument('--search-location', help='Firecrawl search location text, e.g. Germany or a city; not a DataForSEO numeric code')
    p.add_argument('--limit', type=int, default=10)
    p.add_argument('--allow-paid', action='store_true')
    args = p.parse_args()
    try:
        result = research.collect(config_module.load(), **vars(args))
        print(json.dumps(research.summary(result), ensure_ascii=False)); return 0 if result['checked'] else 1
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
        print(json.dumps({'checked': False, 'error': str(exc)})); return 1


if __name__ == '__main__': sys.exit(main())
