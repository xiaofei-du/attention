#!/usr/bin/env python3
"""Stdlib-only entry: verify payload and dependency hashes before loading the SDK."""

import argparse
import json
import os
import sys
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent
sys.path.insert(0, str(BUNDLE))

from nkc.platform_support import data_root, disabled_hook, platform_status
from nkc.payload import payload_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=data_root())
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    arguments = args.arguments or ['status']
    is_hook = arguments[0] == 'hook'
    availability = platform_status()
    if not availability['supported'] and arguments[0] != 'mcp':
        print(json.dumps(disabled_hook(args.data_dir, availability, arguments[1])
                         if is_hook else availability))
        return
    try:
        payload_manifest(BUNDLE)
        from nkc.dependencies import verified_python
        interpreter = verified_python(BUNDLE / 'requirements.txt', args.data_dir.resolve())
        command = [str(interpreter), '-I', str(BUNDLE / 'attention.py'),
                   '--data-dir', str(args.data_dir.resolve()), *arguments]
        os.execv(str(interpreter), command)
    except Exception as error:
        if not is_hook:
            raise
        notice = {'message': 'Attention! could not verify its installation: ' + str(error)[:220] +
                  '. Your coding session can continue; check Attention! setup.'}
        print(json.dumps(disabled_hook(args.data_dir, notice, arguments[1])))


if __name__ == '__main__':
    main()
