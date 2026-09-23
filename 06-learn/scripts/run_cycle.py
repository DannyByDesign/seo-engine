"""Build a durable work packet and optionally invoke the configured scheduled agent."""
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
import fcntl
import json
from scripts.lib import growth, pubstate, strategy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-agent', action='store_true', help='Invoke the explicitly configured agent command with the packet path')
    args = parser.parse_args()
    cfg = config_module.load()
    folder = cfg.state_dir / 'growth'; folder.mkdir(exist_ok=True)
    with (folder / '.cycle-lock').open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'checked': False, 'error': 'growth cycle already active'})); return 1
        jobs = [json.loads(p.read_text()) for p in sorted(folder.glob('*.json'))]
        engine = _find_engine_root(Path(__file__).resolve())
        packet = {'created_at': pubstate.now_iso(), 'repo_root': str(cfg.repo_root),
                  'skill': str(engine / '04-choose/seo-growth/SKILL.md'),
                  'instructions': (engine / '06-learn/growth-cycle.md').read_text(), 'jobs': jobs,
                  'workflow': str(engine / 'workflow/README.md'),
                  'strategy': strategy.status(cfg), 'learning': strategy.learning(cfg, jobs)}
        path = cfg.reports_dir / 'growth-cycle-packet.json'; pubstate.save_json(path, packet)
        result = {'checked': True, 'packet': str(path), 'agent_ran': False}
        if args.execute_agent:
            cmd = (cfg.site.get('growth') or {}).get('agent_command')
            if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) and x for x in cmd):
                result.update(checked=False, blocked='configure growth.agent_command as an argv array; the packet path is appended')
                pubstate.save_json(cfg.reports_dir / 'growth-cycle-last.json', result)
                print(json.dumps(result)); return 1
            run = growth.execute(cfg.repo_root, {'commands': {'agent': cmd + [str(path)]}}, 'agent')
            result.update(agent_ran=True, execution=run)
        pubstate.save_json(cfg.reports_dir / 'growth-cycle-last.json', result)
        print(json.dumps(result))
        return 1 if result.get('execution', {}).get('exit', 0) != 0 else 0


if __name__ == '__main__':
    sys.exit(main())
