#!/usr/bin/env python3
"""Keep the offline helper and copy/paste download command pinned to exact bytes."""
import argparse
import hashlib
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
START = '<!-- attention-uninstall:start -->'
END = '<!-- attention-uninstall:end -->'


def blob_url(content):
    digest = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
    return 'https://api.github.com/repos/xiaofei-du/attention/git/blobs/' + digest


def command(content):
    # The digest is in the trusted instructions, not fetched with the entry it checks.
    template = r'''(
  set -eu
  entry="$(/usr/bin/mktemp "${TMPDIR:-/tmp}/attention-uninstall.XXXXXXXX")"
  trap '/bin/rm -f -- "$entry"' EXIT
  /usr/bin/curl -qfsSL --proto '=https' --proto-redir '=https' --max-time 30 --max-filesize 1048576 \
    -H 'Accept: application/vnd.github.raw+json' \
    @URL@ -o "$entry"
  digest="$(/usr/bin/env -u PERL5OPT -u PERL5LIB /usr/bin/shasum -a 256 "$entry")"
  [ "${digest%% *}" = '@SHA256@' ] || {
    printf '%s\n' 'Attention launcher checksum mismatch; nothing was run.' >&2; exit 1;
  }
  /bin/bash -p "$entry"
)'''
    return template.replace('@URL@', blob_url(content)).replace('@SHA256@', hashlib.sha256(content).hexdigest())


def update(check=False):
    helper = (ROOT / 'scripts/uninstall.py').read_bytes()
    path = ROOT / 'uninstall.sh'
    previous = path.read_text()
    entry = re.sub(r"expected_sha256='[0-9a-f]{64}'",
                   "expected_sha256='" + hashlib.sha256(helper).hexdigest() + "'", previous)
    entry = re.sub(r"helper_url='[^']+'", "helper_url='" + blob_url(helper) + "'", entry)
    changes = {path: entry}
    block = START + '\n```sh\n' + command(entry.encode()) + '\n```\n' + END
    for path in (ROOT / 'README.md', ROOT / 'packaging/PLUGIN-README.md'):
        previous = path.read_text()
        if START not in previous or END not in previous:
            raise ValueError('Missing uninstall command markers: ' + str(path))
        changes[path] = re.sub(re.escape(START) + '.*?' + re.escape(END), lambda _: block,
                               previous, flags=re.S)
    for path, content in changes.items():
        if path.read_text() != content:
            if check:
                raise ValueError('Stale uninstall SHA-256/URL; run python scripts/update_uninstall_command.py: ' + str(path))
            path.write_text(content)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    update(parser.parse_args().check)
