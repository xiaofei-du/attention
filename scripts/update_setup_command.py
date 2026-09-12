#!/usr/bin/env python3
"""Pin the setup helper and regenerate its optional externally verified entry."""
import argparse
import hashlib
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from update_uninstall_command import blob_url, command

ROOT = Path(__file__).resolve().parents[1]
START = '<!-- attention-setup:start -->'
END = '<!-- attention-setup:end -->'


def update(check=False):
    helper = (ROOT / 'scripts/setup.py').read_bytes()
    path = ROOT / 'setup.sh'
    entry = re.sub(r"helper_sha256='[^']+'", "helper_sha256='" + hashlib.sha256(helper).hexdigest() + "'",
                   path.read_text())
    entry = re.sub(r"helper_url='[^']+'", "helper_url='" + blob_url(helper) + "'", entry)
    changes = {path: entry}
    path = ROOT / 'docs/setup.md'
    previous = path.read_text()
    if START not in previous or END not in previous:
        raise ValueError('Missing setup command markers: ' + str(path))
    block = START + '\n```sh\n' + command(entry.encode()).replace('attention-uninstall', 'attention-setup') + '\n```\n' + END
    changes[path] = re.sub(re.escape(START) + '.*?' + re.escape(END), lambda _: block, previous, flags=re.S)
    for path, content in changes.items():
        if path.read_text() != content:
            if check:
                raise ValueError('Stale setup pin/command; run python scripts/update_setup_command.py: ' + str(path))
            path.write_text(content)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    update(parser.parse_args().check)
