#!/usr/bin/env python3
"""Reject Intel wheels tied to runner libraries or macOS newer than 14.2."""

import argparse
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path


def check_native_report(architectures, dependencies, build_commands, install_name=''):
    if architectures.strip() != 'x86_64':
        raise ValueError('Expected an Intel-only dependency binary')
    versions = re.findall(r'(?m)^\s*minos\s+(\d+)\.(\d+)(?:\.(\d+))?\s*$', build_commands)
    if not versions or any(tuple(int(part or '0') for part in version) > (14, 2, 0)
                           for version in versions):
        raise ValueError('Dependency requires macOS newer than 14.2 or has no deployment target')
    linked = [line.strip().split(' (', 1)[0] for line in dependencies.splitlines()[1:] if line.strip()]
    # otool -L starts dylibs with LC_ID_DYLIB, which names this binary itself.
    if linked and install_name and linked[0] == install_name:
        linked = linked[1:]
    if not linked or any(not path.startswith(('/usr/lib/', '/System/Library/Frameworks/')) for path in linked):
        raise ValueError('Wheel must link only macOS system libraries; OpenSSL must be static')


def verify(wheel):
    if not wheel.name.startswith('cryptography-') or not wheel.name.endswith('_x86_64.whl'):
        raise ValueError('Expected a cryptography Intel wheel')
    with zipfile.ZipFile(wheel) as archive, tempfile.TemporaryDirectory() as temporary:
        modules = [name for name in archive.namelist() if name.endswith('.so')]
        if not modules or not any(name.endswith('/LICENSE') for name in archive.namelist()):
            raise ValueError('Wheel is missing its native extension or upstream license')
        for index, name in enumerate(modules):
            binary = Path(temporary) / (str(index) + '.so')
            binary.write_bytes(archive.read(name))
            def output(*command):
                return subprocess.check_output([*command, str(binary)], text=True)
            archs = output('xcrun', 'lipo', '-archs')
            linked = output('xcrun', 'otool', '-L')
            build = output('xcrun', 'vtool', '-show-build')
            identity = output('xcrun', 'otool', '-D').splitlines()[1:]
            print(name, archs.strip(), '\n' + linked + build, flush=True)
            check_native_report(archs, linked, build, identity[0].strip() if identity else '')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path)
    verify(parser.parse_args().wheel)
