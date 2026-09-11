"""Install pinned wheels once, enforcing every dependency hash before execution."""

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


@contextlib.contextmanager
def installation_lock(path):
    with path.open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0)
            lock.write(b'0')
            lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def verified_python(requirements, root):
    identity = json.dumps({'requirements': hashlib.sha256(requirements.read_bytes()).hexdigest(),
                           'python': sys.version, 'platform': sys.platform}, sort_keys=True)
    revision = hashlib.sha256(identity.encode()).hexdigest()[:24]
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    environments = root / 'e'
    environments.mkdir(exist_ok=True, mode=0o700)
    target = environments / revision
    interpreter = target / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    marker = target / '.verified'
    with installation_lock(root / 'dependencies.lock'):
        if target.is_symlink():
            raise ValueError('Attention! dependency directory must not be a symlink')
        if marker.is_file() and marker.read_text() == identity and interpreter.is_file():
            return interpreter
        uv = shutil.which('uv')
        if not uv:
            raise RuntimeError('Install uv and reopen your coding client')
        if target.exists():
            shutil.rmtree(target)
        # Ignore inherited package indexes, Python injection, and project settings.
        environment = {k: v for k, v in os.environ.items()
                       if not k.startswith(('UV_', 'PIP_', 'PYTHON')) and k != 'VIRTUAL_ENV'}
        if os.environ.get('UV_CACHE_DIR'):
            environment['UV_CACHE_DIR'] = os.environ['UV_CACHE_DIR']
        environment['UV_NO_PROGRESS'] = '1'
        commands = [
            [uv, 'venv', '--no-config', '--python', sys.executable, str(target)],
            [uv, 'pip', 'sync', '--no-config', '--python', str(interpreter), '--require-hashes',
             '--only-binary', ':all:', '--index-url', 'https://pypi.org/simple', str(requirements)],
        ]
        try:
            for command in commands:
                result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=180)
                if result.returncode:
                    raise RuntimeError('Attention! dependency verification failed:\n' + result.stderr[-3000:])
            marker.write_text(identity)
            marker.chmod(0o600)
        except BaseException:
            shutil.rmtree(target, ignore_errors=True)
            raise
    return interpreter
