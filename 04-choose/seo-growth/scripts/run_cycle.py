"""Compatibility launcher; implementation lives in its workflow phase."""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parents[3] / '06-learn/scripts/run_cycle.py'), run_name='__main__')
