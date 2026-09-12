#!/usr/bin/env python3
"""Maintainer-only build of a static Intel wheel; never run during installation."""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command, **kwargs):
    print('+', ' '.join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), check=True, **kwargs)


def unpack_source(source, scratch):
    archive = scratch / (source['url'].rsplit('/', 1)[1])
    with urllib.request.urlopen(source['url'], timeout=60) as response:
        archive.write_bytes(response.read())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != source['sha256']:
        raise ValueError('Source SHA-256 mismatch: ' + archive.name)
    with tarfile.open(archive) as tar:
        tar.extractall(scratch, filter='data')
    return scratch / archive.name.removesuffix('.tar.gz')


def build(output):
    if sys.platform != 'darwin' or platform.machine() != 'x86_64':
        raise ValueError('Build on an Intel Mac or the macos-15-intel GitHub runner')
    if output.exists():
        raise ValueError('Choose a new output directory')
    sources = json.loads((ROOT / 'packaging/intel-wheel-sources.json').read_text())
    locked = tomllib.loads((ROOT / 'uv.lock').read_text())
    crypto = next(p for p in locked['package'] if p['name'] == 'cryptography')
    if (crypto['version'], crypto['sdist']['hash']) != (
            sources['cryptography']['version'], 'sha256:' + sources['cryptography']['sha256']):
        raise ValueError('Intel source pins must match uv.lock')
    uv = shutil.which('uv')
    if not uv:
        raise ValueError('Install uv before building')
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='attention-intel-build-') as temporary:
        scratch = Path(temporary).resolve()
        openssl = unpack_source(sources['openssl'], scratch)
        crypto_source = unpack_source(sources['cryptography'], scratch)
        prefix = scratch / 'openssl-static'
        target = sources['deployment_target']
        env = dict(os.environ, MACOSX_DEPLOYMENT_TARGET=target,
                   CFLAGS='-mmacosx-version-min=' + target,
                   OPENSSL_DIR=str(prefix), OPENSSL_STATIC='1',
                   CARGO_TARGET_DIR=str(scratch / 'cargo-target'))
        # System paths only: do not accidentally link a runner's Homebrew OpenSSL.
        env.pop('PKG_CONFIG_PATH', None)
        run(['perl', 'Configure', 'darwin64-x86_64-cc', 'no-shared', 'no-tests',
             '--prefix=' + str(prefix), '--openssldir=' + str(prefix / 'ssl')], cwd=openssl, env=env)
        run(['make', '-j', str(min(os.cpu_count() or 2, 4)), 'build_libs'], cwd=openssl, env=env)
        run(['make', 'install_dev'], cwd=openssl, env=env)
        builder = scratch / 'builder'
        run([uv, 'venv', '--no-config', '--python', sys.executable, builder])
        python = builder / 'bin/python'
        run([uv, 'pip', 'sync', '--no-config', '--python', python, '--require-hashes',
             '--only-binary', ':all:', '--index-url', 'https://pypi.org/simple',
             ROOT / 'packaging/intel-wheel-build-requirements.txt'])
        run([builder / 'bin/maturin', 'build', '--release', '--locked', '--interpreter', python,
             '--target', 'x86_64-apple-darwin', '--out', output], cwd=crypto_source, env=env)
        wheel, = output.glob('*.whl')
        # Check static linkage and deployment target before loading the new code.
        run([sys.executable, ROOT / 'scripts/verify_intel_wheel.py', wheel])
        run([uv, 'pip', 'install', '--no-config', '--python', python, '--no-index', '--no-deps', wheel])
        run([python, '-I', '-c',
             'from cryptography.hazmat.primitives.ciphers.aead import AESGCM; '
             'from cryptography.hazmat.backends.openssl.backend import backend; '
             'cipher=AESGCM(bytes(32)); nonce=bytes(12); '
             'assert cipher.decrypt(nonce,cipher.encrypt(nonce,b"attention",None),None)==b"attention"; '
             'print(backend.openssl_version_text())'])
        shutil.copy2(openssl / 'LICENSE.txt', output / 'LICENSE-OpenSSL.txt')
        manifest = {
            'distribution': 'cryptography', 'version': crypto['version'],
            'wheel': wheel.name, 'sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
            'sources': sources, 'python': sys.version,
            'rust': subprocess.check_output(['rustc', '--version'], text=True).strip(),
            'sdk': subprocess.check_output(['xcrun', '--show-sdk-version'], text=True).strip(),
            'recipe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'build_requirements_sha256': hashlib.sha256(
                (ROOT / 'packaging/intel-wheel-build-requirements.txt').read_bytes()).hexdigest(),
            'commit': os.environ.get('GITHUB_SHA', ''),
            'run_url': ('https://github.com/' + os.environ['GITHUB_REPOSITORY'] + '/actions/runs/' +
                        os.environ['GITHUB_RUN_ID']) if os.environ.get('GITHUB_RUN_ID') else '',
        }
        (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(build(parser.parse_args().output.resolve()))
