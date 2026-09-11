"""Install only our hook handlers; never edit notify or hook-trust state."""

import fcntl
import json
import os
import shlex
import tempfile
import time
from pathlib import Path
from .control_context import CONTROL_MATCHER


PROJECT = Path(__file__).resolve().parent.parent
PYTHON = os.environ.get('ATTENTION_PYTHON', '/usr/bin/python3')
HANDLERS = {
    'UserPromptSubmit': ('prompt', 'no-keyboard-code: summary context'),
    'Stop': ('stop', 'no-keyboard-code: spoken summary'),
    'PreToolUse': ('control-context', 'no-keyboard-code: session control context'),
}


def definition(provider='codex'):
    if provider not in ('codex', 'claude-code'):
        raise ValueError('Unsupported hook provider')
    result = {'hooks': {}}
    for event, (action, label) in HANDLERS.items():
        if event == 'PreToolUse' and provider == 'codex':
            continue
        arguments = [PYTHON, str(PROJECT / 'run.py'), 'hook', action]
        if provider != 'codex':
            arguments.extend(['--provider', provider])
        command = shlex.join(arguments)
        handler = {'type': 'command', 'command': command, 'timeout': 5, 'statusMessage': label}
        # Finish the durable handoff before the host exits. Playback already
        # runs in a detached worker; the hook never waits for spoken audio.
        result['hooks'][event] = [{'hooks': [handler]}]
        if event == 'PreToolUse':
            result['hooks'][event][0]['matcher'] = CONTROL_MATCHER
    return result


def _ours(handler):
    return (isinstance(handler, dict)
            and handler.get('statusMessage') in {v[1] for v in HANDLERS.values()}
            and str(PROJECT / 'run.py') in handler.get('command', ''))


def _update(home, installing, provider):
    definitions = definition(provider)
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    path = home / ('settings.json' if provider == 'claude-code' else 'hooks.json')
    with (home / '.nkc-hooks.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = path.read_bytes() if path.exists() else None
        data = json.loads(previous) if previous is not None else {'hooks': {}}
        if not isinstance(data, dict) or not isinstance(data.get('hooks', {}), dict):
            raise ValueError('Existing ' + path.name + ' has an unsupported shape')
        hooks = data.setdefault('hooks', {})
        for event in HANDLERS:
            groups = hooks.get(event, [])
            if not isinstance(groups, list):
                raise ValueError('Existing hook event is not a list')
            retained = []
            for group in groups:
                if not isinstance(group, dict) or not isinstance(group.get('hooks', []), list):
                    raise ValueError('Existing hook group is malformed')
                kept = [h for h in group.get('hooks', []) if not _ours(h)]
                if len(kept) == len(group.get('hooks', [])):
                    retained.append(group)
                elif kept:
                    retained.append(dict(group, hooks=kept))
            if retained:
                hooks[event] = retained
            else:
                hooks.pop(event, None)
        if installing:
            for event, groups in definitions['hooks'].items():
                hooks.setdefault(event, []).extend(groups)
        encoded = (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode()
        if previous == encoded:
            return path
        if (path.read_bytes() if path.exists() else None) != previous:
            raise RuntimeError('Hooks changed during installation; no overwrite performed')
        if previous is not None:
            backup = home / (path.name + '.nkc-backup-' + str(time.time_ns()))
            backup.write_bytes(previous)
            backup.chmod(0o600)
        if not installing and not hooks and set(data) == {'hooks'}:
            if path.exists():
                path.unlink()
            return path
        fd, temporary = tempfile.mkstemp(prefix='.nkc-hooks-', dir=str(home))
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return path


def install_hooks(home, provider='codex'):
    return _update(home, True, provider)


def uninstall_hooks(home, provider='codex'):
    return _update(home, False, provider)
