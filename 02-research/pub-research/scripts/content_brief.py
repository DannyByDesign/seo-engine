"""Prepare, confirm or inspect article-specific publishable operator knowledge."""
import argparse
import json
import os
import sys
from pathlib import Path

override = os.environ.get('SEO_ENGINE_ROOT')
candidates = ([Path(override)] if override else []) + list(Path(__file__).resolve().parents)
root = next((p for p in candidates if (p / 'scripts/lib/config.py').is_file()), None)
if root is None:
    raise SystemExit('Set SEO_ENGINE_ROOT to the engine directory when copying individual skills.')
sys.path.insert(0, str(root))
from scripts.lib import config, content, pubstate


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--action', choices=['prepare', 'confirm', 'status'], required=True)
    p.add_argument('--content-id', required=True, help='publication:PUBLICATION:SLUG or page:/target-path')
    p.add_argument('--file', help='JSON containing only proposed publishable material')
    p.add_argument('--confirm-digest', help='Exact proposal digest explicitly approved by the operator')
    p.add_argument('--operator', help='Identity of the operator who approved the proposed use')
    p.add_argument('--confirmation', help='Operator confirmation; never infer this from an interview answer')
    args = p.parse_args()
    target = config.load().repo_root
    try:
        if args.action == 'prepare':
            if not args.file: p.error('--file is required for prepare')
            result = content.prepare(target, args.content_id, json.loads(Path(args.file).read_text()))
        elif args.action == 'confirm':
            ref = content.confirm(target, args.content_id, args.confirm_digest, args.operator, args.confirmation)
            result = {'status': 'approved', 'content_brief': ref}
        else:
            result = pubstate.load_json(content.record_path(target, args.content_id), {'status': 'awaiting_interview'})
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({'checked': False, 'error': str(exc)}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
