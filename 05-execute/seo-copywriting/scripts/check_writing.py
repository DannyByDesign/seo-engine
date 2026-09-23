"""Check a draft with LanguageTool; save suggestions without rewriting source."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import writing_examples
from scripts.lib import config, languagetool


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--file', required=True)
    p.add_argument('--format', choices=['markdown', 'html', 'text'], default='markdown')
    p.add_argument('--language', help='Language variant such as en-US, en-GB, de-DE; default from config')
    p.add_argument('--level', choices=['default', 'picky'])
    args = p.parse_args()
    try:
        result = languagetool.check(config.load(), Path(args.file).read_text(), format=args.format,
                                   language=args.language, level=args.level)
    except (OSError, ValueError) as exc:
        result = {'checked': False, 'error': str(exc)}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['checked'] else 1


if __name__ == '__main__': sys.exit(main())
