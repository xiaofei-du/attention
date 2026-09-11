"""Portable payload integrity checks; these hashes are not publisher signatures."""

import hashlib
import json
from pathlib import Path


def payload_manifest(bundle):
    manifest = json.loads((bundle / 'payload.json').read_text())
    files = manifest['files']
    if not isinstance(files, dict) or not files:
        raise ValueError('Invalid Attention! payload manifest')
    for relative, digest in files.items():
        path = Path(relative)
        if (not path.parts or path.is_absolute() or '..' in path.parts or
                not isinstance(digest, str) or len(digest) != 64):
            raise ValueError('Invalid Attention! payload path or hash')
        actual = bundle / path
        if (any((bundle / Path(*path.parts[:i])).is_symlink() for i in range(1, len(path.parts) + 1)) or
                not actual.is_file() or hashlib.sha256(actual.read_bytes()).hexdigest() != digest):
            raise ValueError('Attention! payload failed integrity check: ' + relative)
    encoded = json.dumps(files, sort_keys=True, separators=(',', ':')).encode()
    return files, hashlib.sha256(encoded).hexdigest()[:16]
