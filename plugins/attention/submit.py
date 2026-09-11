#!/usr/bin/env python3
"""Submit current-turn speech through a local broker, without opening SQLite."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nkc.submission import submit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', required=True)
    parser.add_argument('--token', required=True)
    args = parser.parse_args()
    raw = sys.stdin.buffer.read(8001)
    if len(raw) > 8000:
        raise ValueError('Summary exceeds eight kilobytes')
    print(json.dumps(submit(args.socket, args.token, json.loads(raw))))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        print('Summary was not submitted: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
