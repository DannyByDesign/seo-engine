"""Compatibility launcher; implementation lives in its workflow phase."""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parents[3] / '02-research/scripts/research_market.py'), run_name='__main__')
