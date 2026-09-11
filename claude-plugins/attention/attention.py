#!/usr/bin/env python3
"""Portable plugin entry point; platform checks precede native imports."""

import argparse
import json
import os
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nkc.platform_support import data_root, disabled_hook, platform_status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=data_root())
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    arguments = args.arguments or ['status']
    availability = platform_status()
    is_hook = arguments[0] == 'hook'
    is_mcp = arguments[0] == 'mcp'
    if not availability['supported']:
        if is_mcp:
            import asyncio
            os.environ['ATTENTION_SERVER_NAME'] = 'attention'
            from nkc.mcp_server import serve
            asyncio.run(serve(args.data_dir / 'state'))
        elif is_hook:
            print(json.dumps(disabled_hook(args.data_dir, availability, arguments[1] if len(arguments) > 1 else '')))
        else:
            print(json.dumps(availability))
        return

    from nkc.bootstrap import dispatch
    try:
        dispatch(Path(__file__).resolve().parent, args.data_dir.resolve(), arguments)
    except Exception as error:
        # Setup problems must never block the original coding turn.
        if not is_hook:
            raise
        notice = {'message': 'Attention! could not prepare speech: ' + str(error)[:220] +
                  '. Your coding session can continue; inspect Attention! setup before retrying.'}
        print(json.dumps(disabled_hook(args.data_dir, notice, arguments[1] if len(arguments) > 1 else '')))


if __name__ == '__main__':
    main()
