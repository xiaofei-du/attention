"""Platform checks must stay importable without Apple's audio modules."""

import hashlib
import os
import platform
from pathlib import Path


def platform_status(system=None, version=None, machine=None):
    system = platform.system() if system is None else system
    version = platform.mac_ver()[0] if version is None else version
    machine = platform.machine() if machine is None else machine
    try:
        parts = tuple(int(part) for part in version.split('.'))
    except ValueError:
        parts = ()
    supported = system == 'Darwin' and (parts + (0, 0))[:2] >= (14, 2) and machine in ('arm64', 'x86_64')
    return {'supported': supported, 'status': 'ready' if supported else 'unsupported_platform',
            'system': system, 'version': version, 'architecture': machine,
            'message': ('Attention! is ready on this Mac.' if supported else
                        'Attention! requires macOS 14.2 or later on an Apple Silicon or Intel Mac. '
                        'Spoken notifications are disabled; your coding session can continue normally.')}


def data_root():
    if os.environ.get('ATTENTION_DATA_DIR'):
        return Path(os.environ['ATTENTION_DATA_DIR']).expanduser().resolve()
    if platform.system() == 'Darwin':
        return Path.home() / 'Library' / 'Application Support' / 'Attention'
    if platform.system() == 'Windows':
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'Attention'
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local' / 'state'))) / 'attention'


def disabled_hook(root, status, action):
    if action != 'prompt':
        return {}
    # Only a tiny warning receipt is stored; no queue/database/audio setup.
    key = hashlib.sha256(status['message'].encode()).hexdigest()[:16]
    try:
        notices = Path(root) / 'notices'
        notices.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (notices / key).open('x') as file:
            file.write(status['message'])
    except (FileExistsError, OSError):
        return {}
    return {'systemMessage': status['message']}
