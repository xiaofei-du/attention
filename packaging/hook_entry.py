"""Embedded in hook commands so a deleted plugin cache is not the entry point."""
import hashlib
import json
import os
import platform
import runpy
import sys
from pathlib import Path

PINNED_DIGEST = '{{payload_digest}}'


def data_root():
    if os.environ.get('ATTENTION_DATA_DIR'):
        return Path(os.environ['ATTENTION_DATA_DIR']).expanduser().resolve()
    if platform.system() == 'Darwin':
        return Path.home() / 'Library/Application Support/Attention'
    if platform.system() == 'Windows':
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'Attention'
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'attention'


def verify(bundle):
    if bundle.is_symlink() or (bundle / 'payload.json').is_symlink():
        raise ValueError('Symlinked payload')
    files = json.loads((bundle / 'payload.json').read_text())['files']
    encoded = json.dumps(files, sort_keys=True, separators=(',', ':')).encode()
    if hashlib.sha256(encoded).hexdigest() != PINNED_DIGEST or 'launch.py' not in files:
        raise ValueError('Wrong payload version')
    for name, digest in files.items():
        relative = Path(name)
        if relative.is_absolute() or not relative.parts or '..' in relative.parts:
            raise ValueError('Unsafe payload path')
        if any((bundle / Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts) + 1)):
            raise ValueError('Symlinked payload file')
        if hashlib.sha256((bundle / relative).read_bytes()).hexdigest() != digest:
            raise ValueError('Changed payload file')


def main():
    arguments = sys.argv[2:]
    root = data_root()
    runtime = root / 'r' / PINNED_DIGEST[:16]
    try:
        if (root / 'r').is_symlink():
            raise ValueError('Symlinked runtime directory')
        for bundle in (runtime, Path(sys.argv[1])):
            if not bundle.exists() and not bundle.is_symlink():
                continue
            verify(bundle)
            entry = bundle / 'launch.py'
            sys.argv = [str(entry), *arguments]
            runpy.run_path(str(entry), run_name='__main__')
            return
    except (OSError, ValueError, KeyError, TypeError):
        pass
    # A missing/changed installation must not fail the coding turn or choose
    # another session's runtime. Prompt reports the repair action; Stop is quiet.
    message = 'Attention! could not find its verified version. Reload or reinstall the plugin to restore spoken notifications.'
    print(json.dumps({'systemMessage': message} if arguments[:2] == ['hook', 'prompt'] else {}))


if __name__ == '__main__':
    main()
